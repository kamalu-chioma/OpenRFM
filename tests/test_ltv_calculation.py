import unittest

import pandas as pd

from app import calculate_ltv


class LTVCalculationEdgeCaseTests(unittest.TestCase):
    def test_single_transaction_customer(self):
        # One purchase over a two-year tenure: frequency/year is 0.5, and the
        # tenure factor should cancel out so LTV equals order value * frequency.
        average_order_value = 250.0
        purchase_frequency_per_year = 0.5
        customer_tenure_years = 2.0

        ltv = calculate_ltv(
            average_order_value, purchase_frequency_per_year, customer_tenure_years
        )

        self.assertAlmostEqual(ltv, 250.0)

    def test_very_short_tenure(self):
        # A customer whose tenure is clipped to a single day (as the
        # regression pipeline does) has a very small tenure-in-years value,
        # which inflates purchase_frequency_per_year. The product should
        # remain numerically stable and equal order value * frequency.
        tenure_days = 1
        tenure_years = tenure_days / 365.25
        frequency = 3
        average_order_value = 100.0
        purchase_frequency_per_year = frequency / tenure_years

        ltv = calculate_ltv(
            average_order_value, purchase_frequency_per_year, tenure_years
        )

        self.assertAlmostEqual(ltv, average_order_value * frequency)

    def test_zero_purchase_frequency(self):
        ltv = calculate_ltv(
            average_order_value=500.0,
            purchase_frequency_per_year=0.0,
            customer_tenure_years=3.0,
        )

        self.assertEqual(ltv, 0.0)

    def test_near_zero_purchase_frequency(self):
        average_order_value = 500.0
        purchase_frequency_per_year = 1e-6
        customer_tenure_years = 3.0

        ltv = calculate_ltv(
            average_order_value, purchase_frequency_per_year, customer_tenure_years
        )

        self.assertAlmostEqual(
            ltv, average_order_value * purchase_frequency_per_year * customer_tenure_years
        )
        self.assertLess(ltv, 1e-2)

    def test_very_high_transaction_amounts(self):
        average_order_value = 1_000_000.0
        purchase_frequency_per_year = 12
        customer_tenure_years = 5.0

        ltv = calculate_ltv(
            average_order_value, purchase_frequency_per_year, customer_tenure_years
        )

        self.assertAlmostEqual(ltv, 60_000_000.0)

    def test_vectorized_series_inputs_cover_multiple_edge_cases(self):
        # calculate_ltv should behave identically for scalar and Series
        # inputs, as used during the vectorised RFM pipeline calculation.
        average_order_value = pd.Series([250.0, 100.0, 500.0, 1_000_000.0])
        purchase_frequency_per_year = pd.Series([0.5, 3 / (1 / 365.25), 0.0, 12])
        customer_tenure_years = pd.Series([2.0, 1 / 365.25, 3.0, 5.0])

        ltv = calculate_ltv(
            average_order_value, purchase_frequency_per_year, customer_tenure_years
        )

        expected = pd.Series([250.0, 300.0, 0.0, 60_000_000.0])
        pd.testing.assert_series_equal(ltv, expected, check_exact=False, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
