from flask import Flask, request, jsonify
from datetime import datetime
from models.quest import quests_collection, users_collection

app = Flask(__name__)

def get_next_user_id():
    counter = users_collection.database.counters.find_one_and_update(
        {"_id": "userId"},   # separate counter for users
        {"$inc": {"seq": 1}}, 
        upsert=True,         # create if missing
        return_document=True
    )
    return counter["seq"]

def get_next_quest_id():
    counter = quests_collection.database.counters.find_one_and_update(
        {"_id": "questId"},      # the counter document
        {"$inc": {"seq": 1}},    # increment seq by 1
        upsert=True,             # create if missing
        return_document=True     # return the new document after increment
    )
    return counter["seq"]

# -----------------------------
# QUEST ROUTES
# -----------------------------
# CREATE a quest
@app.route("/quests", methods=["POST"])
def create_quest():
    data = request.get_json()

    quest_id = get_next_quest_id()  # generate unique questId
    created_at = datetime.utcnow().strftime("%Y-%m-%d")  # ISO date

    quest_doc = {
        "questId": quest_id,
        "userId": data.get("userId"),
        "title": data.get("title"),
        "subject": data.get("subject"),
        "description": data.get("description"),
        "suggested_minutes": data.get("suggested_minutes"),
        "deadline": data.get("deadline"),
        "visibility": data.get("visibility"),
        "status": data.get("status", "prepare"),  # prepare | active | done
        "created_at": created_at
    }

    quests_collection.insert_one(quest_doc)
    quest_doc.pop("_id", None)

    return jsonify(quest_doc), 201

# GET quests for a specific user
@app.route("/quests", methods=["GET"])
def get_user_quests():
    user_id = request.args.get("userId")  # read from URL parameter
    if not user_id:
        return jsonify({"error": "userId parameter is required"}), 400
    
    user_id = int(user_id)  # convert to number if you are using numeric userId

    user_quests = list(quests_collection.find({"userId": user_id}, {"_id": 0}))
    for quest in user_quests:
        # remove None fields
        for key in list(quest.keys()):
            if quest[key] is None:
                quest.pop(key)

    return jsonify(user_quests), 200

# UPDATE quest info
@app.route("/quests", methods=["PATCH"])
def update_quest():
    data = request.get_json()

    quest_id = data.get("questId")
    user_id = data.get("userId")

    if not quest_id or not user_id:
        return jsonify({"error": "userId and questId are required"}), 400

    update_fields = {}
    for field in ["title", "description", "difficulty"]:
        if field in data:
            update_fields[field] = data[field]

    if not update_fields:
        return jsonify({"error": "No fields to update"}), 400

    result = quests_collection.update_one(
        {"userId": user_id, "questId": quest_id},
        {"$set": update_fields}
    )

    if result.matched_count == 0:
        return jsonify({"error": "Quest not found"}), 404

    return jsonify({"message": "Quest updated successfully!"}), 200


@app.route("/quests/status", methods=["PATCH"])
def change_quest_status():
    data = request.get_json()

    user_id = data.get("userId")
    quest_id = data.get("questId")
    status = data.get("status")

    if not user_id or not quest_id or not status:
        return jsonify({"error": "userId, questId, and status are required"}), 400

    if status not in ["prepare", "active", "done"]:
        return jsonify({"error": "Invalid status"}), 400

    result = quests_collection.update_one(
        {"userId": user_id, "questId": quest_id},
        {"$set": {"status": status}}
    )

    if result.matched_count == 0:
        return jsonify({"error": "Quest not found"}), 404

    return jsonify({
        "userId": user_id,
        "questId": quest_id,
        "status": status
    }), 200

# DELETE a quest
@app.route("/quests", methods=["DELETE"])
def delete_quest():
    data = request.get_json()
    user_id = data.get("userId")
    quest_id = data.get("questId")

    quest = quests_collection.find_one({"questId": quest_id, "userId": user_id})
    if not quest:
        return jsonify({"error": "Quest not found for this user"}), 404

    quests_collection.delete_one({"questId": quest_id, "userId": user_id})
    remaining_quests = list(quests_collection.find({"userId": user_id}, {"questId": 1, "_id": 0}))
    
    remaining_ids = [q["questId"] for q in remaining_quests]

    return jsonify({
        "userId": user_id,
        "quests": remaining_ids
    }), 200
    
# -----------------------------
# USER ROUTES
# -----------------------------

@app.route("/users", methods=["POST"])
def register_user():
    data = request.get_json()

    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    user_id = get_next_user_id()

    user_doc = {
        "userId": user_id, 
        "password": password,
        "email": email,
        "created_at": datetime.now().strftime("%Y-%m-%d")
    }

    users_collection.insert_one(user_doc)
    user_doc.pop("_id", None)

    return jsonify(user_doc), 201

# LOGIN API
@app.route("/users/login", methods=["POST"])
def login_user():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    user = users_collection.find_one(
        {"email": email, "password": password},
        {"_id": 0, "userId": 1}
    )

    if user:
        return jsonify({"userId": user["userId"]}), 200
    else:
        return jsonify({"userId": None}), 200

# UPDATE user info
@app.route("/users", methods=["PATCH"])
def update_user():
    data = request.get_json()
    user_id = data.get("userId")

    if not user_id:
        return jsonify({"error": "userId is required"}), 400

    update_fields = {}
    if "nickname" in data:
        update_fields["nickname"] = data["nickname"]
    if "role" in data:
        update_fields["role"] = data["role"]

    if not update_fields:
        return jsonify({"error": "No fields to update"}), 400

    result = users_collection.update_one(
        {"userId": user_id},
        {"$set": update_fields}
    )

    if result.matched_count == 0:
        return jsonify({"error": "User not found"}), 404

    user = users_collection.find_one(
        {"userId": user_id},
        {"_id": 0, "password": 0, "email": 0}
    )

    return jsonify(user), 200


# DELETE a user
@app.route("/users", methods=["DELETE"])
def delete_user():
    data = request.get_json()
    user_id = data.get("userId")

    if not user_id:
        return jsonify({"status": "Failures"}), 400

    user_result = users_collection.delete_one({"userId": user_id})
    quests_collection.delete_many({"userId": user_id})

    if user_result.deleted_count == 0:
        return jsonify({"status": "Failure"}), 404

    return jsonify({"status": "Success"}), 200


# -----------------------------
# RUN SERVER
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
