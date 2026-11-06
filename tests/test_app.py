import time

import pytest
from fastapi.testclient import TestClient

from paper_translator.app import create_app


@pytest.fixture
def client(config, server):
    with TestClient(create_app(config, server), base_url="http://127.0.0.1") as test_client:
        yield test_client


def upload(client, data):
    return client.post("/api/papers", files={"file": ("paper.pdf", data, "application/pdf")})


def wait_until_done(client, paper_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        paper = client.get(f"/api/papers/{paper_id}").json()
        if paper["status"] == "done":
            return paper
        time.sleep(0.02)
    raise AssertionError("translation did not finish")


def test_upload_translates_and_exports_markdown(client, pdf_bytes):
    response = upload(client, pdf_bytes)
    assert response.status_code == 201
    paper_id = response.json()["id"]

    paper = wait_until_done(client, paper_id)
    assert paper["title"] == "A Small Paper About Testing"
    assert paper["done"] == paper["total"] == 2

    markdown = client.get(f"/api/papers/{paper_id}/export.md").text
    assert markdown.startswith("# A Small Paper About Testing")
    assert "訳: This is the first paragraph" in markdown


def test_same_pdf_is_not_translated_twice(client, server, pdf_bytes):
    paper_id = upload(client, pdf_bytes).json()["id"]
    wait_until_done(client, paper_id)
    calls = len(server.calls)

    assert upload(client, pdf_bytes).json()["id"] == paper_id
    assert len(server.calls) == calls


def test_invalid_pdf_is_rejected_without_leftovers(client, config):
    response = upload(client, b"not a pdf")

    assert response.status_code == 400
    assert list((config.data_dir / "papers").iterdir()) == []


def test_page_image_is_served_within_range(client, pdf_bytes):
    paper_id = upload(client, pdf_bytes).json()["id"]

    image = client.get(f"/api/papers/{paper_id}/pages/0.png")
    assert (image.status_code, image.headers["content-type"]) == (200, "image/png")
    assert client.get(f"/api/papers/{paper_id}/pages/9.png").status_code == 404


def test_delete_removes_files(client, config, pdf_bytes):
    paper_id = upload(client, pdf_bytes).json()["id"]
    wait_until_done(client, paper_id)

    assert client.delete(f"/api/papers/{paper_id}").status_code == 204
    assert client.get(f"/api/papers/{paper_id}").status_code == 404
    assert not (config.data_dir / "papers" / paper_id).exists()


def test_unknown_paper_returns_404(client):
    assert client.get("/api/papers/unknown").status_code == 404


def test_requests_from_other_hosts_are_rejected(client):
    assert client.get("/api/papers", headers={"host": "evil.example"}).status_code == 400


def test_static_files_are_revalidated(client):
    assert client.get("/app.js").headers["cache-control"] == "no-cache"
