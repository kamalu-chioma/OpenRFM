from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_file
import os
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from werkzeug.utils import secure_filename
from flask_socketio import SocketIO
from flask_swagger_ui import get_swaggerui_blueprint
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import re
from fuzzywuzzy import process


app = Flask(__name__)
socketio = SocketIO(app)
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {"csv", "xlsx"}

limiter = Limiter(
    get_remote_address,  # Uses IP address for rate-limiting
    app=app,  # Attach to the app
    default_limits=["1000 per day", "100 per hour"]  # Global limits
)

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[-1].lower() in ALLOWED_EXTENSIONS

@app.route("/")
def index():
    return render_template("index.html")

MAX_FILE_SIZE_MB = 90  

@app.route("/upload", methods=["POST"])
@limiter.limit("10 per minute")  # ⏳ Limits file uploads to 10 per minute per user
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files["file"]
    
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    if allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)

        # Check file size
        file.seek(0, os.SEEK_END)
        file_size = file.tell() / (1024 * 1024)  # Convert to MB
        file.seek(0)

        if file_size > MAX_FILE_SIZE_MB:
            return jsonify({"error": f"File too large. Max size is {MAX_FILE_SIZE_MB}MB"}), 400

        file.save(file_path)  # ✅ Save the file if it passes validation
        return jsonify({"message": "File uploaded successfully", "file_path": file_path}), 200

    return jsonify({"error": "Invalid file format. Please upload a CSV or Excel file."}), 400


@app.route("/process_rfm", methods=["POST"])
def process_rfm():
    try:
        data = request.get_json()
        file_path = data.get("file_path")
        selected_clusters = data.get("cluster_size")

        if not file_path or not os.path.exists(file_path):
            return jsonify({"error": "File not found or invalid path"}), 400

        socketio.emit("progress", {"message": "Reading File..."})

        file_extension = file_path.rsplit(".", 1)[-1].lower()
        if file_extension == "csv":
            df = pd.read_csv(file_path, encoding="utf-8", low_memory=False)
        elif file_extension == "xlsx":
            df = pd.read_excel(file_path, engine="openpyxl")
        else:
            return jsonify({"error": "Unsupported file type"}), 400



        COLUMN_MAP = {
            "CustomerID": ["CustomerID", "Cust_ID", "customer id", "client_id", "UserID"],
            "TransactionDate": ["TransactionDate", "InvoiceDate", "Order_Date", "TransDate", "Purchase_Date"],
            "TransactionAmount": ["TransactionAmount", "Amount", "SalesAmount", "Revenue", "Transaction_Value"]
        }

        def find_best_match(columns, possible_names):
            """ Matches column names using regex and fuzzy matching """
            for expected, variants in possible_names.items():
                matches = [col for col in columns if any(re.search(pattern, col, re.IGNORECASE) for pattern in variants)]
                if matches:
                    return expected, matches[0]  # Return standard name + matched column
            return None, None  # No match found

        detected_columns = {}
        for key, variants in COLUMN_MAP.items():
            standard_name, matched_name = find_best_match(df.columns, {key: variants})
            if matched_name:
                detected_columns[standard_name] = matched_name

        required_columns = ["CustomerID", "TransactionDate", "TransactionAmount"]
        if not all(col in detected_columns for col in required_columns):
            return jsonify({"error": f"Missing required columns: {set(required_columns) - set(detected_columns.keys())}"}), 400

        df = df.rename(columns=detected_columns)  # ✅ Rename columns to standard format



        socketio.emit("progress", {"message": "Processing Data..."})
        df.fillna(0, inplace=True)

        if set(["CustomerID", "TransactionDate", "TransactionAmount"]).issubset(df.columns):
            df["TransactionDate"] = pd.to_datetime(df["TransactionDate"], errors='coerce')
        elif set(["InvoiceDate", "Quantity", "UnitPrice", "CustomerID"]).issubset(df.columns):
            df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"], errors='coerce')
            df["TransactionAmount"] = df["Quantity"] * df["UnitPrice"]
            df.rename(columns={"InvoiceDate": "TransactionDate"}, inplace=True)
            df = df[["CustomerID", "TransactionDate", "TransactionAmount"]]
        else:
            return jsonify({"error": "Invalid CSV format. Expected columns missing."}), 400

        socketio.emit("progress", {"message": "Calculating RFM Metrics..."})
        df.dropna(subset=["CustomerID", "TransactionDate"], inplace=True)
        current_date = datetime.today()

        customer_dates = (
            df.groupby("CustomerID")["TransactionDate"]
            .agg(FirstPurchaseDate="min", LastPurchaseDate="max")
            .reset_index()
        )
        customer_dates["Recency"] = (
            current_date - customer_dates["LastPurchaseDate"]
        ).dt.days

        frequency_df = df.groupby("CustomerID").size().reset_index(name="Frequency")
        monetary_df = df.groupby("CustomerID")["TransactionAmount"].sum().reset_index(name="Monetary")

        rfm_df = (
            customer_dates
            .merge(frequency_df, on="CustomerID")
            .merge(monetary_df, on="CustomerID")
        )

        rfm_df["CustomerTenureDays"] = (
            current_date - rfm_df["FirstPurchaseDate"]
        ).dt.days.clip(lower=1)
        rfm_df["CustomerTenureYears"] = rfm_df["CustomerTenureDays"] / 365.25
        rfm_df["AverageOrderValue"] = np.where(
            rfm_df["Frequency"] > 0,
            rfm_df["Monetary"] / rfm_df["Frequency"],
            0,
        )
        rfm_df["PurchaseFrequencyPerYear"] = rfm_df["Frequency"] / np.maximum(
            rfm_df["CustomerTenureYears"],
            1 / 365.25,
        )
        # Lifetime Value (LTV) approximates customer revenue over their observed lifespan.
        # Formula: LTV = Average Order Value * Purchase Frequency (per year) * Customer Tenure (years)
        rfm_df["LTV"] = (
            rfm_df["AverageOrderValue"]
            * rfm_df["PurchaseFrequencyPerYear"]
            * rfm_df["CustomerTenureYears"]
        )

        numeric_columns = [
            "Recency",
            "Frequency",
            "Monetary",
            "CustomerTenureDays",
            "CustomerTenureYears",
            "AverageOrderValue",
            "PurchaseFrequencyPerYear",
            "LTV",
        ]
        rfm_df[numeric_columns] = rfm_df[numeric_columns].fillna(0)

        scaler = StandardScaler()
        rfm_df[["Recency", "Frequency", "Monetary"]] = scaler.fit_transform(rfm_df[["Recency", "Frequency", "Monetary"]])

        # **Ensure Clustering Matches User Selection**
        socketio.emit("progress", {"message": "Determining Optimal Number of Clusters..."})

        unique_customers = len(rfm_df)
        max_clusters = min(10, unique_customers)

        if unique_customers < 2:
            return jsonify({"error": "Not enough unique customers for clustering"}), 400

        if selected_clusters == "auto":
            distortions = []
            K_range = range(2, max_clusters + 1)
            for k in K_range:
                kmeans = KMeans(n_clusters=k, random_state=42)
                kmeans.fit(rfm_df[["Recency", "Frequency", "Monetary"]])
                distortions.append(kmeans.inertia_)
            optimal_clusters = np.argmax(np.diff(distortions)) + 2
        else:
            optimal_clusters = int(selected_clusters)
            if optimal_clusters < 2:
                optimal_clusters = 2  

        optimal_clusters = min(optimal_clusters, unique_customers)

        socketio.emit("progress", {"message": f"Applying {optimal_clusters} Clusters..."})

        # **Apply KMeans**
        kmeans = KMeans(n_clusters=optimal_clusters, random_state=42, n_init="auto")
        rfm_df["Cluster"] = kmeans.fit_predict(rfm_df[["Recency", "Frequency", "Monetary"]])

        # **Sort Clusters by Average Recency to Keep Order Consistent**
        cluster_summary = rfm_df.groupby("Cluster")[["Recency", "Frequency", "Monetary"]].mean()
        sorted_clusters = cluster_summary.sort_values(by="Recency").index.tolist()

        cluster_labels = {}

        # **Assign Segments Based on Sorted Clusters**
        for i, cluster in enumerate(sorted_clusters):
            if i == 0:
                cluster_labels[cluster] = "Loyal Customers"
            elif i == 1:
                cluster_labels[cluster] = "At Risk Customers"
            elif i == 2:
                cluster_labels[cluster] = "Occasional Buyers"
            elif i == 3:
                cluster_labels[cluster] = "Lost Customers"
            elif i == 4:
                cluster_labels[cluster] = "High-Value Customers"
            elif i == 5:
                cluster_labels[cluster] = "Low-Value Customers"
            elif i == 6:
                cluster_labels[cluster] = "New & Engaged Customers"
            elif i == 7:
                cluster_labels[cluster] = "Big Spenders"
            elif i == 8:
                cluster_labels[cluster] = "Mid-Value Customers"
            else:
                cluster_labels[cluster] = "Other"

        rfm_df["Cluster Meaning"] = rfm_df["Cluster"].map(cluster_labels)

        # **🔥 Assign Churn Labels Dynamically**
        def assign_churn_label(row):
            if row["Cluster Meaning"] in ["At Risk Customers", "Lost Customers"]:
                return "Yes"
            elif row["Recency"] > cluster_summary["Recency"].median() and row["Frequency"] < cluster_summary["Frequency"].median():
                return "Yes"
            elif row["Cluster Meaning"] in ["Loyal Customers", "New & Engaged Customers", "Big Spenders"]:
                return "No"
            else:
                return "Maybe"

        rfm_df["Likely_Churn"] = rfm_df.apply(assign_churn_label, axis=1)

        socketio.emit("progress", {"message": "RFM Analysis Complete!"})

        output_file = os.path.join(UPLOAD_FOLDER, "rfm_results.csv")
        rfm_df.to_csv(output_file, index=False)

        return jsonify({
            "data": rfm_df[["CustomerID", "Cluster", "Cluster Meaning", "Likely_Churn", "LTV"]].to_dict(orient="records"),
            "download_link": "/download_csv"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500





# Define Swagger UI Route
SWAGGER_URL = "/api/docs"  # URL for Swagger UI
API_URL = "/static/swagger.json"  # Path to Swagger JSON file

swagger_ui_blueprint = get_swaggerui_blueprint(SWAGGER_URL, API_URL, config={"app_name": "RFM API"})
app.register_blueprint(swagger_ui_blueprint, url_prefix=SWAGGER_URL)




@app.route("/download_csv", methods=["GET"])
def download_csv():
    file_path = os.path.join(UPLOAD_FOLDER, "rfm_results.csv")
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    else:
        return jsonify({"error": "File not found"}), 404

if __name__ == "__main__":
    socketio.run(app, debug=True)
