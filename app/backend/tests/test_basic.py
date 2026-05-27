import time


def test_healthz(client):
    # Send GET request to /healthz
    response = client.get("/healthz")

    # Assert: response should be 200 OK
    assert response.status_code == 200

    # Assert: response body should match expected JSON
    assert response.json() == {"status": "ok"}


def test_root_endpoint(client):
    # Send GET request to root endpoint
    response = client.get("/")

    # Assert: response should be 200 OK
    assert response.status_code == 200

    data = response.json()

    # Assert: response should contain service metadata
    assert "service" in data
    assert "version" in data


def test_db_healthz(client, monkeypatch):
    # Monkeypatch check_db to avoid real DB access
    def fake_check_db():
        return None

    monkeypatch.setattr("src.main.check_db", fake_check_db)

    # Send GET request to /db/healthz
    response = client.get("/db/healthz")

    # Assert: response should be 200 OK
    assert response.status_code == 200

    # Assert: response body indicates DB is healthy
    assert response.json() == {"db": "ok"}


def test_metrics_endpoint(client):
    # Send GET request to /metrics
    response = client.get("/metrics")

    # Assert: response should be 200 OK
    assert response.status_code == 200

    # Assert: response body should contain Prometheus metrics
    assert "http_requests_total" in response.text


def test_metrics_use_normalized_route_labels(client):
    # Create a task so we can call a dynamic route with a real UUID.
    created_response = client.post("/api/tasks", json={"title": "Metric route test"})
    assert created_response.status_code == 201

    task_id = created_response.json()["id"]

    # Call the endpoint that uses a path parameter: /api/tasks/{task_id}.
    # The real request URL contains a UUID, but Prometheus labels must use
    # the normalized FastAPI route template instead of the raw URL.
    response = client.get(f"/api/tasks/{task_id}")
    assert response.status_code == 200

    # Fetch Prometheus metrics after the dynamic route was called.
    metrics_response = client.get("/metrics")
    assert metrics_response.status_code == 200

    # The metrics output should contain the normalized route template.
    assert "/api/tasks/{task_id}" in metrics_response.text

    # The concrete UUID must not appear in metrics labels, otherwise every task
    # would create a separate Prometheus time series and cause high cardinality.
    assert task_id not in metrics_response.text


def test_create_task_success(client):
    # Send valid payload to create a new task
    payload = {"title": "Buy milk"}
    response = client.post("/api/tasks", json=payload)

    # Assert: should return 201 Created
    assert response.status_code == 201

    data = response.json()

    # Assert: response should include id, title, done=false, timestamps
    assert "id" in data
    assert data["title"] == "Buy milk"
    assert data["done"] is False
    assert "created_at" in data
    assert "updated_at" in data

    # Assert: Location header points to the created resource
    assert response.headers["Location"] == f"/api/tasks/{data['id']}"


def test_create_task_invalid(client):
    # Send invalid payload (empty title after strip)
    payload = {"title": "   "}
    response = client.post("/api/tasks", json=payload)

    # Assert: should return 422 Unprocessable Entity
    assert response.status_code == 422

    data = response.json()
    assert data["detail"][0]["msg"].startswith("Value error")


def test_get_task_by_id(client):
    # Create a task
    created = client.post("/api/tasks", json={"title": "Find me"}).json()
    tid = created["id"]

    # Fetch the task by id
    response = client.get(f"/api/tasks/{tid}")

    # Assert: should return 200 OK
    assert response.status_code == 200

    data = response.json()

    # Assert: returned task matches created task
    assert data["id"] == tid
    assert data["title"] == "Find me"


def test_get_task_not_found(client):
    # Use valid but non-existent task id
    missing_id = "00000000-0000-0000-0000-000000000000"

    response = client.get(f"/api/tasks/{missing_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"


def test_update_task_title(client):
    # Create a task
    created = client.post("/api/tasks", json={"title": "Old title"}).json()
    tid = created["id"]

    # Update task title
    response = client.patch(f"/api/tasks/{tid}", json={"title": "New title"})

    # Assert: should return 200 OK
    assert response.status_code == 200

    data = response.json()

    # Assert: title should be updated
    assert data["title"] == "New title"


def test_update_task_done(client):
    # Create a task
    created = client.post("/api/tasks", json={"title": "Complete me"}).json()
    tid = created["id"]

    # Update done flag
    response = client.patch(f"/api/tasks/{tid}", json={"done": True})

    # Assert: should return 200 OK
    assert response.status_code == 200

    data = response.json()

    # Assert: done flag should be updated
    assert data["done"] is True


def test_update_task_invalid_title(client):
    # Create a task
    created = client.post("/api/tasks", json={"title": "Valid title"}).json()
    tid = created["id"]

    # Update title with invalid whitespace-only value
    response = client.patch(f"/api/tasks/{tid}", json={"title": "   "})

    # Assert: should return 422 Unprocessable Entity
    assert response.status_code == 422

    data = response.json()
    assert data["detail"][0]["msg"].startswith("Value error")


def test_update_task_empty_payload(client):
    # Create a task
    created = client.post("/api/tasks", json={"title": "Test"}).json()
    tid = created["id"]

    # Send empty update payload
    response = client.patch(f"/api/tasks/{tid}", json={})

    # Assert: should return 400 Bad Request
    assert response.status_code == 400
    assert response.json()["detail"] == "No fields provided for update"


def test_update_task_not_found(client):
    # Use valid but non-existent task id
    missing_id = "00000000-0000-0000-0000-000000000000"

    # Attempt to update non-existent task
    response = client.patch(f"/api/tasks/{missing_id}", json={"title": "Ghost"})

    # Assert: should return 404 Not Found
    assert response.status_code == 404


def test_delete_task_ok(client):
    # Create a task
    created = client.post("/api/tasks", json={"title": "to delete"}).json()
    tid = created["id"]

    # Delete it
    response = client.delete(f"/api/tasks/{tid}")
    assert response.status_code == 204  # No Content

    # Verify it's gone
    response2 = client.get(f"/api/tasks/{tid}")
    assert response2.status_code == 404


def test_delete_task_not_found(client):
    # Use valid but non-existent task id
    missing_id = "00000000-0000-0000-0000-000000000000"

    # Attempt to delete non-existent task
    response = client.delete(f"/api/tasks/{missing_id}")

    # Assert: should return 404 Not Found
    assert response.status_code == 404


def test_list_contains_created_task(client):
    # Create one task
    created = client.post("/api/tasks", json={"title": "Item A"}).json()

    # List tasks
    response = client.get("/api/tasks")
    assert response.status_code == 200
    data = response.json()

    # Assert: the created task is present
    assert any(t["id"] == created["id"] for t in data)


def test_list_pagination_and_order(client):
    # Create 3 items
    client.post("/api/tasks", json={"title": "First"})
    client.post("/api/tasks", json={"title": "Second"})
    client.post("/api/tasks", json={"title": "Third"})

    # Expect newest first (created_at desc)
    page1 = client.get("/api/tasks?limit=2&offset=0").json()
    page2 = client.get("/api/tasks?limit=2&offset=2").json()

    # Assert page sizes
    assert len(page1) == 2
    assert len(page2) >= 1  # third item may be the only one

    # Optional: check that page1 items are not duplicated in page2
    ids1 = {t["id"] for t in page1}
    ids2 = {t["id"] for t in page2}
    assert ids1.isdisjoint(ids2)


def test_list_limit_too_large(client):
    response = client.get("/api/tasks?limit=201")
    assert response.status_code == 422


def test_list_offset_negative(client):
    response = client.get("/api/tasks?offset=-1")
    assert response.status_code == 422


def test_filter_done_true(client):
    # Create one incomplete task
    client.post("/api/tasks", json={"title": "Todo"})

    # Create one completed task
    task = client.post("/api/tasks", json={"title": "Done"}).json()
    client.patch(f"/api/tasks/{task['id']}", json={"done": True})

    # Request only completed tasks
    response = client.get("/api/tasks?done=true")

    # Assert: should return 200 OK
    assert response.status_code == 200

    data = response.json()

    # Assert: filtered list should not be empty
    assert len(data) >= 1

    # Assert: all returned tasks are done
    assert all(t["done"] is True for t in data)


def test_filter_done_false(client):
    # Create one incomplete task
    client.post("/api/tasks", json={"title": "Todo A"})

    # Create one completed task
    task = client.post("/api/tasks", json={"title": "Todo B"}).json()
    client.patch(f"/api/tasks/{task['id']}", json={"done": True})

    # Request only incomplete tasks
    response = client.get("/api/tasks?done=false")

    # Assert: should return 200 OK
    assert response.status_code == 200

    data = response.json()

    # Assert: filtered list should not be empty
    assert len(data) >= 1

    # Assert: all returned tasks are not done
    assert all(t["done"] is False for t in data)


def test_list_limit_min_boundary(client):
    # Create a couple of tasks
    client.post("/api/tasks", json={"title": "One"})
    client.post("/api/tasks", json={"title": "Two"})

    # Request minimum allowed limit
    response = client.get("/api/tasks?limit=1")

    assert response.status_code == 200
    data = response.json()

    # Only one item should be returned
    assert len(data) == 1


def test_list_limit_max_boundary(client):
    # Create multiple tasks
    for i in range(5):
        client.post("/api/tasks", json={"title": f"Task {i}"})

    # Request maximum allowed limit
    response = client.get("/api/tasks?limit=200")

    assert response.status_code == 200
    data = response.json()

    # All tasks should be returned (<= 200)
    assert len(data) >= 5


def test_update_task_changes_updated_at(client):
    # Create a task
    created = client.post("/api/tasks", json={"title": "Before update"}).json()
    tid = created["id"]
    original_updated_at = created["updated_at"]

    # Small delay to ensure timestamp difference
    time.sleep(1.1)

    # Update the task
    response = client.patch(f"/api/tasks/{tid}", json={"title": "After update"})
    assert response.status_code == 200

    data = response.json()

    # updated_at should change after PATCH
    assert data["updated_at"] != original_updated_at
