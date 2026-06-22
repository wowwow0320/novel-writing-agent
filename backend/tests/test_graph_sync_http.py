import unittest

import httpx

from app.services.graph_sync import (
    Neo4jHttpError,
    _is_database_unavailable_error,
    _parse_query_api_rows,
    _parse_tx_commit_rows,
    _raise_neo4j_http_error,
)


class GraphSyncHttpTests(unittest.TestCase):
    def test_parse_query_api_rows(self) -> None:
        body = {"data": {"fields": ["name", "cnt"], "values": [["Hina", 2], ["Mingi", 1]]}}

        self.assertEqual(
            _parse_query_api_rows(body),
            [{"name": "Hina", "cnt": 2}, {"name": "Mingi", "cnt": 1}],
        )

    def test_parse_transaction_api_rows(self) -> None:
        body = {
            "results": [
                {
                    "columns": ["name", "cnt"],
                    "data": [{"row": ["Hina", 2]}, {"row": ["Mingi", 1]}],
                }
            ],
            "errors": [],
        }

        self.assertEqual(
            _parse_tx_commit_rows(body),
            [{"name": "Hina", "cnt": 2}, {"name": "Mingi", "cnt": 1}],
        )

    def test_database_unavailable_error_is_actionable(self) -> None:
        response = httpx.Response(
            404,
            json={
                "errors": [
                    {
                        "code": "Neo.TransientError.General.DatabaseUnavailable",
                        "message": "Requested database is not available. Requested database name: 'neo4j'.",
                    }
                ]
            },
        )

        with self.assertRaises(Neo4jHttpError) as cm:
            _raise_neo4j_http_error(response, database="neo4j", api="query/v2")

        self.assertTrue(_is_database_unavailable_error(cm.exception))
        self.assertIn("neo4j", str(cm.exception))
        self.assertIn("사용 불가", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
