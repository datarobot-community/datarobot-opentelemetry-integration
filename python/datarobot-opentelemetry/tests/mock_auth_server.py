# Copyright 2026 DataRobot, Inc. and its affiliates.
#
# All rights reserved.
#
# DataRobot, Inc. Confidential.
#
# This is unpublished proprietary source code of DataRobot, Inc.
# and its affiliates.
#
# The copyright notice above does not evidence any actual or intended
# publication of such source code.

import json
from datetime import datetime
from datetime import timedelta
from http.server import HTTPServer
from http.server import SimpleHTTPRequestHandler
from os import getenv
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent


def _fixture_path(env_var: str, default_filename: str) -> Path:
    configured = getenv(env_var)
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else FIXTURES_DIR / path
    return FIXTURES_DIR / default_filename


with open(
    _fixture_path("MOCK_AUTH_SERVER_AUTH_RESPONSE_JSON_PATH", "auth_response.json"), "r", encoding="utf-8"
) as f:
    AUTH_RESPONSE = json.load(f)


with open(
    _fixture_path("MOCK_AUTH_SERVER_ENTITLEMENT_RESPONSE_JSON_PATH", "entitlement_response.json"),
    "r",
    encoding="utf-8",
) as f:
    ENTITLEMENT_RESOURCE = json.load(f)


with open(
    _fixture_path("MOCK_AUTH_SERVER_ACESS_CONTROL_RESOURCE_JSON_PATH", "access_control_resource.json"),
    "r",
    encoding="utf-8",
) as f:
    ACCESS_CONTROL_RESOURCE = json.load(f)


class AuthHandler(SimpleHTTPRequestHandler):
    def _set_headers(self, status_code: int = 200) -> None:
        self.send_response(status_code)
        self.send_header("Content-type", "application/json")
        self.end_headers()

    def do_GET(self) -> None:
        print(f"Received GET request for path: {self.path}")
        if self.path == "/api/v2/account/info/":
            # Return 200 and JSON for the /auth endpoint
            self._set_headers()
            response = AUTH_RESPONSE
            self.wfile.write(json.dumps(response).encode("utf-8"))
        else:
            # Handle other paths with 404
            self._set_headers(404)
            response = {"status": "error", "message": "Not found"}
            self.wfile.write(json.dumps(response).encode("utf-8"))

    def do_POST(self) -> None:
        if self.path == "/api/v2/accessControls/evaluate/":
            # Return 200 and JSON for the /accessControls/evaluate/ endpoint
            # all requested resources will be marked ass allowed
            # except one that has no_permissions in resource ID
            self._set_headers()
            content_length = int(self.headers["Content-Length"])
            post_data_bytes = self.rfile.read(content_length)
            post_data_str = post_data_bytes.decode("UTF-8")
            post_data = json.loads(post_data_str)
            subject_id = post_data["subjectId"]
            resource = ACCESS_CONTROL_RESOURCE
            resources = []
            for res in post_data["resources"]:
                res_json = dict(resource)
                res_json["resourceId"] = res["resourceId"]
                if "no_permissions" in res["resourceId"]:
                    res_json["effectivePermissions"] = []
                    res_json["allowed"] = False
                resources.append(res_json)
            response = {"subjectId": subject_id, "resources": resources}
            self.wfile.write(json.dumps(response).encode("utf-8"))
        elif self.path == ("/token"):
            self._set_headers()
            expires_in = datetime.utcnow() + timedelta(days=1)
            response = {"access_token": "Token", "expires_in": expires_in.timestamp()}
            self.wfile.write(json.dumps(response).encode("utf-8"))
        elif self.path == "/api/v2/entitlements/evaluate/":
            self._set_headers()
            response = ENTITLEMENT_RESOURCE
            self.wfile.write(json.dumps(response).encode("utf-8"))
        else:
            # Handle other paths with 404
            self._set_headers(404)
            response = {"status": "error", "message": "Not found"}
            self.wfile.write(json.dumps(response).encode("utf-8"))


def run_server(host: str = "localhost", port: int = 80) -> None:
    server_address = (host, port)
    httpd = HTTPServer(server_address, AuthHandler)
    print(f"Server running at http://{host}:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    host = str(getenv("MOCK_AUTH_SERVER_HOST", "localhost"))
    port = int(getenv("MOCK_AUTH_SERVER_PORT", "8880"))
    run_server(host, port)
