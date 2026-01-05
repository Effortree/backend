# models/quest.py
# Defines the structure of a quest
# This is basically your JSON mapped to MongoDB

from pymongo import MongoClient

client = MongoClient("mongodb+srv://effortee_user:CFR!qHc4f$yG7v$@effortree.soic3n4.mongodb.net/?appName=effortree")  # connect to MongoDB
db = client['effortee']                             # database
quests_collection = db['quests']                    # collection
users_collection = db["users"]                   