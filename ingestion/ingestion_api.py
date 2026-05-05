import requests
import pandas as pd

BASE_URL = "https://fake-store-api.mock.beeceptor.com/api"

# ------------------ EXTRACT ------------------
def fetch_data(endpoint):
    url = f"{BASE_URL}/{endpoint}"
    data = requests.get(url).json()
    return pd.DataFrame(data)


# ------------------ TRANSFORM ------------------
def transform_data(orders, products):

    # STEP 1: EXPLODE ITEMS
    orders_expanded = orders.explode("items").reset_index(drop=True)
    items_df = pd.json_normalize(orders_expanded["items"])

    orders_flat = pd.concat(
        [orders_expanded.drop(columns=["items"]), items_df],
        axis=1
    )

    # STEP 2: ADD DATE
    orders_flat["order_date"] = pd.Timestamp.now()

    # STEP 3: JOIN PRODUCTS
    df = pd.merge(orders_flat, products, on="product_id")

    # STEP 4: SELECT COLUMNS
    df = df[[
        "order_id",
        "order_date",
        "user_id",
        "product_id",
        "category",
        "quantity",
        "price"
    ]]

    df.rename(columns={
        "user_id": "store_id",
        "price": "unit_price"
    }, inplace=True)

    # STEP 5: REMOVE NULL VALUES
    df = df.dropna()

    # STEP 6: DERIVED COLUMNS
    df["total_amount"] = df["quantity"] * df["unit_price"]
    df["order_month"] = df["order_date"].dt.month
    df["order_day"] = df["order_date"].dt.day

    return df


# ------------------ MAIN ------------------
if __name__ == "__main__":

    orders = fetch_data("orders")
    products = fetch_data("products")

    final_df = transform_data(orders, products)

    print(final_df.head())

    # Save output
    final_df.to_csv("cleaned_orders.csv", index=False)
