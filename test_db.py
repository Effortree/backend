from pymongo import MongoClient
try:
    client = MongoClient("mongodb://localhost:27017/")
    client.admin.command('ping')
    print("✅ Database connected successfully!")
except Exception as e:
    print(f"❌ Connection failed: {e}")