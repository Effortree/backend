# models/quest.py
# Defines the structure of a quest
# This is basically your JSON mapped to MongoDB

from pymongo import MongoClient
from config import MONGO_URL

client = MongoClient(MONGO_URL)  # connect to MongoDB
db = client['effortee']                             # database
quests_collection = db['quests']                    # collection
users_collection = db["users"]       
messages_collection = db['messages']            