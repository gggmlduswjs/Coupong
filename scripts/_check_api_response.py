"""WING API list_products 응답 구조 확인"""
import sys, os, json
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from dotenv import load_dotenv
load_dotenv()

from app.database import SessionLocal, init_db
from app.models.account import Account
from scripts.sync_coupang_products import create_wing_client

init_db()
db = SessionLocal()

account = db.query(Account).filter(Account.account_name == "007-book").first()
client = create_wing_client(account)

# 1페이지만 가져오기
params = {"vendorId": client.vendor_id, "maxPerPage": "2"}
result = client._request("GET", client.SELLER_PRODUCTS_PATH, params=params)

data = result.get("data", [])
if isinstance(data, list) and data:
    product = data[0]
    print("=== list response keys ===")
    print(sorted(product.keys()))
    print()

    items = product.get("items", [])
    print(f"items count: {len(items)}")
    if items:
        print("items[0] keys:", sorted(items[0].keys()))
        print("salePrice:", items[0].get("salePrice"))
        print("originalPrice:", items[0].get("originalPrice"))
    else:
        print("items is EMPTY")

    print()
    print("=== full product sample (truncated) ===")
    print(json.dumps(product, indent=2, ensure_ascii=False)[:2000])
elif isinstance(data, dict):
    products = data.get("products", data.get("items", []))
    if products:
        product = products[0]
        print("=== list response (nested) keys ===")
        print(sorted(product.keys()))
        items = product.get("items", [])
        print(f"items count: {len(items)}")
        if items:
            print("items[0] keys:", sorted(items[0].keys()))
            print("salePrice:", items[0].get("salePrice"))
        print()
        print(json.dumps(product, indent=2, ensure_ascii=False)[:2000])

db.close()
