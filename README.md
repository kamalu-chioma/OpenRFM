## OpenRFM - RFM Customer Analyzer

## Welcome to RFM Customer Analyzer

OpenRFM is an open-source tool that helps businesses analyze customer behavior through **Recency, Frequency, and Monetary (RFM)** analysis. Understand your customers' buying behavior to improve marketing strategies, retention, and revenue generation.

## Why Segment Customers?

Not all customers are the same. By clustering customers based on their behavior, businesses can:
- **Tailor marketing**: Create personalized campaigns based on customer behavior.
- **Improve retention**: Identify high-value and at-risk customers.
- **Maximize revenue**: Optimize targeting to drive sales and reduce churn.

## What RFM Reveals:
- **High-value customers**: Identify those who generate the most revenue.
- **Churn prediction**: Detect customers likely to stop engaging.
- **Marketing optimization**: Tailor campaigns to target different customer segments effectively.

## How It Works (RFM):
- **Recency (R)**: Days since the customer's last purchase.
- **Frequency (F)**: How often the customer makes a purchase.
- **Monetary (M)**: Total amount the customer spends.

## Who Is This For?
- **Businesses tracking customer engagement**: Improve customer relationships and sales.
- **Marketers predicting churn & loyalty**: Retain high-value customers.
- **Data scientists analyzing customer behavior**: Dive deeper into customer segmentation and trends.

➡ Go to the **Upload Section** below to get started.

---

## Upload Customer Data

### File Format:
- Accepted Formats: **CSV** and **XLSX**
- Your file should include the following columns:
  - **CustomerID**: Unique identifier for each customer.
  - **TransactionDate**: Date of the transaction (YYYY-MM-DD).
  - **TransactionAmount**: Amount spent on the transaction.

Example format:
```csv
CustomerID,TransactionDate,TransactionAmount
1001,2024-01-01,150.00
1002,2024-02-10,200.00
1003,2024-03-15,75.50

CustomerID,TransactionDate,TransactionAmount
1001,2024-01-01,150.00
1002,2024-02-10,200.00
1003,2024-03-15,75.50
```

**Cluster Size:** Auto (Optimal Calculation)

Once you upload the file, the tool will process the data and display the top 5 rows of the processed data.

## Installation

Clone the repository:

```bash
git clone https://github.com/kamalu-chioma/OpenRFM.git
cd OpenRFM
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the application:

```bash
python app.py
```

## License

OpenRFM is open-source software, distributed under the MIT License. See the LICENSE file for more details.
