import os
import tempfile
import unittest
from datetime import datetime, timedelta

import pandas as pd

from app import app


class ProcessRFMIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        app.config["TESTING"] = True
        self.client = app.test_client()

    def _post_process_request(self, file_path: str, cluster_size="auto"):
        response = self.client.post(
            "/process_rfm",
            json={"file_path": file_path, "cluster_size": cluster_size},
        )
        return response

    def test_csv_with_varied_headers_and_extra_columns(self):
        base_date = datetime(2023, 1, 1)
        rows = []
        for idx in range(1, 6):
            for order in range(2):
                rows.append(
                    {
                        "client_identifier": f"CUST-{idx:03d}",
                        "sale_date": base_date + timedelta(days=idx * 10 + order),
                        "gross_amount": f"$ {110 + idx * 15 + order}",
                        "engagement_score": 70 + idx,
                        "channel": "email" if order % 2 == 0 else "social",
                    }
                )
        df = pd.DataFrame(rows)

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "orders.csv")
            df.to_csv(file_path, index=False)

            response = self._post_process_request(file_path, cluster_size=3)

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertIn("data", payload)
        self.assertEqual(len(payload["data"]), len({row["client_identifier"] for row in rows}))
        self.assertIn("schema_mapping", payload)
        self.assertEqual(payload["schema_mapping"].get("client_identifier"), "CustomerID")
        self.assertEqual(payload["schema_mapping"].get("sale_date"), "TransactionDate")
        self.assertEqual(payload["schema_mapping"].get("gross_amount"), "TransactionAmount")
        self.assertIn("messages", payload)

    def test_xlsx_with_mixed_column_order(self):
        base_date = datetime(2023, 6, 1)
        rows = []
        for idx in range(1, 7):
            for order in range(2):
                rows.append(
                    {
                        "region": "EU" if idx % 2 == 0 else "US",
                        "purchase_timestamp": (base_date + timedelta(days=idx * 5 + order)).strftime("%Y/%m/%d"),
                        "member_code": f"MBR-{idx:02d}",
                        "net_spend": 180 + idx * 20 + order * 5,
                        "coupon_used": order % 2 == 0,
                    }
                )
        df = pd.DataFrame(rows)[["member_code", "purchase_timestamp", "net_spend", "region", "coupon_used"]]

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "transactions.xlsx")
            df.to_excel(file_path, index=False)

            response = self._post_process_request(file_path, cluster_size="auto")

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertEqual(payload["schema_mapping"].get("member_code"), "CustomerID")
        self.assertEqual(payload["schema_mapping"].get("purchase_timestamp"), "TransactionDate")
        self.assertEqual(payload["schema_mapping"].get("net_spend"), "TransactionAmount")
        self.assertGreater(len(payload["data"]), 0)

    def test_schema_inference_failure_returns_actionable_message(self):
        base_date = datetime(2023, 3, 1)
        rows = []
        for idx in range(1, 5):
            rows.append(
                {
                    "customer_code": f"CC-{idx:02d}",
                    "transaction_dt": base_date + timedelta(days=idx * 4),
                    "units_sold": 3 * idx,
                }
            )
        df = pd.DataFrame(rows)

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "missing_amount.csv")
            df.to_csv(file_path, index=False)

            response = self._post_process_request(file_path, cluster_size=2)

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertIn("error", payload)
        self.assertIn("TransactionAmount", payload["error"])
        self.assertIn("details", payload)
        suggestions = payload["details"].get("suggestions", {})
        self.assertIn("TransactionAmount", suggestions)
        self.assertIsNotNone(suggestions["TransactionAmount"])
        self.assertIn("best_column", suggestions["TransactionAmount"])


if __name__ == "__main__":
    unittest.main()
