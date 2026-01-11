# models/chat.py
from pymongo import MongoClient
import os
from config import MONGO_URL

client = MongoClient(MONGO_URL)

db = client["effortree"]
messages_collection = db["messages"]