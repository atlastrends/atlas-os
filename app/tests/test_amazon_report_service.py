import os
from unittest import TestCase

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.services.amazon_report_service import _match_headers, parse_report


REPORT_HEADERS = [
    "Date",
    "Category",
    "Product Title",
    "Asin",
    "Clicks",
    "Indirect Items Ordered",
    "Direct Items Ordered",
    "Items Ordered",
    "Direct Conversion Rate",
    "Order Quantity",
    "Product Conversion Rate",
    "Order Conversion Rate",
    "Commission Rate",
    "Ordered Revenue",
    "Items Shipped",
    "Items Returned",
    "Items Shipped Revenue",
    "Items Shipped Earnings",
    "Items Returned Revenue",
    "Items Returned Earnings",
    "Total Earnings",
]


class AmazonReportHeaderTests(TestCase):
    def test_prefers_sales_totals_over_rates_and_partial_quantities(self):
        mapping = _match_headers(REPORT_HEADERS)

        self.assertEqual(mapping["qty"], 14)
        self.assertEqual(mapping["revenue"], 16)
        self.assertEqual(mapping["commission"], 20)

    def test_parses_sales_from_current_linked_product_report(self):
        row = [
            "2026-08-06",
            "Home",
            "Example product",
            "B000000001",
            "25",
            "1",
            "2",
            "3",
            "8.00%",
            "3",
            "12.00%",
            "12.00%",
            "4.00%",
            "150.00",
            "2",
            "0",
            "100.00",
            "4.00",
            "0.00",
            "0.00",
            "4.00",
        ]
        csv_data = (
            ",".join(REPORT_HEADERS) + "\n" + ",".join(row) + "\n"
        ).encode()

        parsed = parse_report("Linked-Product.csv", csv_data, "BR")

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["qty"], 2)
        self.assertEqual(parsed[0]["revenue"], 100.0)
        self.assertEqual(parsed[0]["commission"], 4.0)
