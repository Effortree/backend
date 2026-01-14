from flask import Flask, request, jsonify
from datetime import datetime
from models.quest import quests_collection, users_collection, messages_collection, pages_collection
from flask_cors import CORS
from pymongo import ReturnDocument
from bson.objectid import ObjectId
from tutor_agent import run_tutor
from summary_agent import summarize_logs
import config

app = Flask(__name__)
CORS(app)  # allows all origins (quick fix)

from analytics import analytics_bp
app.register_blueprint(analytics_bp)

# -----------------------------
# UTILITY: Build conversation history
# -----------------------------
def build_history(messages, limit=6):
    """
    messages: list of {role, content}
    Returns a string of the last N messages formatted for the LLM.
    """
    recent = messages[-limit:]

    history_lines = []
    for m in recent:
        role = "User" if m["role"] == "user" else "Assistant"
        history_lines.append(f"{role}: {m['content']}")

    return "\n".join(history_lines)

# -----------------------------
# Generic counter function
# -----------------------------
def get_next_id(counter_name):
    """
    Returns the next integer ID for the given counter.
    counter_name: string, e.g., "userId", "pageId", "questId", "messageId"
    """
    counter = users_collection.database.counters.find_one_and_update(
        {"_id": counter_name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    return counter["seq"]

# -----------------------------
# Specific helper functions
# -----------------------------
def get_next_user_id():
    return get_next_id("userId")

def get_next_page_id():
    return get_next_id("pageId")

def get_next_quest_id():
    return get_next_id("questId")

def get_next_message_id():
    return get_next_id("messageId")

def now_iso():
    return datetime.utcnow().isoformat() + "Z"

# =========
# generate tutor reply (temporary mock)
# =========             
def generate_tutor_reply(quick_action, content):
    if quick_action == "hint":
        return "Here is a hint to guide your thinking."
    elif quick_action == "example":
        return "Here is an example to help you understand."
    elif quick_action == "why":
        return "Here is the reasoning behind this concept."
    elif quick_action == "summary":
        return "Here is a short summary."
    elif quick_action == "application":
        return "Here is how you can apply this concept."
    else:  # text
        return f"You said: {content}"


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
        "topic": data.get("topic"),
        "description": data.get("description"),

        "status": "prepare",
        "visibility": data.get("visibility", "private"),

        "suggested_minutes": data.get("suggested_minutes", 0),
        "deadline": data.get("deadline"),

        #ANALYTICS
        "spent_logs": [],

        "created_at": datetime.utcnow().strftime("%Y-%m-%d"),
        "updated_at": datetime.utcnow().strftime("%Y-%m-%d")
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
    
    update_fields["updated_at"] = datetime.utcnow().strftime("%Y-%m-%d")

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
        {"$set": {
            "status": status,
            "updated_at": datetime.utcnow().strftime("%Y-%m-%d")
        }}

    )

    if result.matched_count == 0:
        return jsonify({"error": "Quest not found"}), 404

    return jsonify({
        "userId": user_id,
        "questId": quest_id,
        "status": status
    }), 200
    
@app.route("/quests/spent", methods=["POST"])
def add_spent_log():
    data = request.get_json()

    user_id = data.get("userId")
    quest_id = data.get("questId")
    spent_at = data.get("spent_at")        # YYYY-MM-DD
    spent_minutes = data.get("spent_minutes")

    if not all([user_id, quest_id, spent_at, spent_minutes]):
        return jsonify({"error": "Missing required fields"}), 400

    spent_log = {
        "spent_at": spent_at,
        "spent_minutes": int(spent_minutes)
    }

    result = quests_collection.update_one(
        {"userId": int(user_id), "questId": int(quest_id)},
        {
            "$push": {"spent_logs": spent_log},
            "$set": {"updated_at": datetime.utcnow().strftime("%Y-%m-%d")}
        }
    )

    if result.matched_count == 0:
        return jsonify({"error": "Quest not found"}), 404

    return jsonify({
        "message": "Study time logged",
        "questId": quest_id,
        "spent_log": spent_log
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

# ===========
# TUTORS
# ===========
@app.route("/tutors", methods=["POST"])
def send_message():
    data = request.get_json()

    user_id = data.get("userId")
    quick_action = data.get("quickAction")
    content = data.get("content", "")

    if not user_id or not quick_action:
        return jsonify({"error": "userId and quickAction are required"}), 400

    if quick_action == "text" and not content:
        return jsonify({"error": "content is required when quickAction is text"}), 400

    seq_id = get_next_message_id()  # e.g., 1001

    # -------------------------
    # USER MESSAGE
    # -------------------------
    user_message = {
        "messageId": f"{seq_id}-U",
        "userId": user_id,
        "role": "user",
        "content": content,
        "createdAt": datetime.utcnow().isoformat() + "Z"
    }
    messages_collection.insert_one(user_message)

    # -------------------------
    # ASSISTANT MESSAGE
    # -------------------------
    try:
        # 1) Load previous messages (last 50)
        previous_messages = list(
            messages_collection.find(
                {"userId": user_id},
                {"role": 1, "content": 1, "_id": 0}
            ).sort("createdAt", 1).limit(50)
        )

        # 2) Build history string
        history_text = build_history(previous_messages, limit=6)

        # 3) For quick actions, include last tutor response
        if quick_action in ["why", "hint", "example", "summary", "application"]:
            last_assistant = list(
                messages_collection.find(
                    {"userId": user_id, "role": "assistant"},
                    {"content": 1, "_id": 0}
                ).sort("createdAt", -1).limit(1)
            )
            last_text = last_assistant[0]["content"] if last_assistant else ""
            content_to_send = (
                f"User clicked '{quick_action}' on the last tutor answer:\n{last_text}\n"
                "Respond appropriately to the user."
            )
        else:
            content_to_send = content

        # 4) Call tutor LLM with memory
        assistant_content = run_tutor(content_to_send, history_text)

    except Exception as e:
        print("❌ Tutor AI error:", e)
        assistant_content = "Sorry, I couldn't generate a response right now."

    created_at_assistant = datetime.utcnow().isoformat() + "Z"

    assistant_message = {
        "messageId": f"{seq_id}-A",
        "userId": user_id,
        "role": "assistant",
        "content": assistant_content,
        "createdAt": created_at_assistant
    }
    messages_collection.insert_one(assistant_message)

    user_message.pop("_id", None)
    assistant_message.pop("_id", None)

    return jsonify({
        "userMessage": user_message,
        "assistantMessage": assistant_message
    }), 200

# =========
# GET CONVO FROM A USER
# ========
@app.route("/tutors", methods=["GET"])
def get_user_messages():
    user_id = request.args.get("userId")

    if not user_id:
        return jsonify({"error": "userId parameter is required"}), 400

    user_id = int(user_id)

    messages = list(
        messages_collection.find(
            {"userId": user_id},
            {"_id": 0}
        ).sort("createdAt", 1)  # SORT BY TIME (ASC)
    )

    return jsonify(messages), 200

# -----------------------------
# CREATE a new quick note (page)
# -----------------------------
@app.route("/logs", methods=["POST"])
def create_page():
    data = request.get_json()

    if not all(k in data for k in ["userId", "content", "type"]):
        return jsonify({"error": "userId, content, and type are required"}), 400

    page_doc = {
        "pageId": get_next_page_id(),   # ✅ readable
        "userId": int(data["userId"]),
        "type": data["type"],
        "content": data["content"],
        "tags": data.get("tags", []),
        "createdAt": now_iso(),
        "updatedAt": now_iso()
    }

    pages_collection.insert_one(page_doc)
    page_doc.pop("_id", None)
    return jsonify(page_doc), 201

# -----------------------------
# UPDATE a page
# -----------------------------
@app.route("/logs", methods=["PATCH"])
def update_page():
    data = request.get_json()

    page_id = data.get("pageId")
    user_id = data.get("userId")

    if not page_id or not user_id:
        return jsonify({"error": "pageId and userId are required"}), 400

    update_fields = {k: data[k] for k in ["content", "tags", "type"] if k in data}
    update_fields["updatedAt"] = now_iso()

    updated_page = pages_collection.find_one_and_update(
        {"pageId": page_id, "userId": int(user_id)},
        {"$set": update_fields},
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0}
    )

    if not updated_page:
        return jsonify({"error": "Page not found"}), 404

    return jsonify(updated_page), 200

# -----------------------------
# DELETE a page (quick note)
# -----------------------------
@app.route("/logs", methods=["DELETE"])
def delete_page():
    page_id = request.args.get("pageId")
    user_id = request.args.get("userId")

    if not page_id or not user_id:
        return jsonify({"error": "pageId and userId are required"}), 400

    result = pages_collection.delete_one({
        "pageId": int(page_id),   # 🔑 THIS is the fix
        "userId": int(user_id)
    })

    if result.deleted_count == 0:
        return jsonify({"message": "Page not found"}), 404

    return jsonify({"message": "Success"}), 200

# -----------------------------
# GET logs by date (for any date)
# -----------------------------
@app.route("/logs", methods=["GET"])
def get_logs_by_date():
    user_id = request.args.get("userId")
    date = request.args.get("date")  # YYYY-MM-DD

    if not user_id or not date:
        return jsonify({"error": "userId and date are required"}), 400

    logs = list(pages_collection.find(
        {"userId": int(user_id), "createdAt": {"$regex": f"^{date}"}},
        {"_id": 0}
    ))

    return jsonify({"entries": logs}), 200

# -----------------------------
# GET summary of today's summary (MOCK)
# -----------------------------
@app.route("/logs/summary", methods=["GET"])
def get_logs_summary():
    user_id = request.args.get("userId")
    date = request.args.get("date")  # OPTIONAL

    if not user_id:
        return jsonify({"error": "userId is required"}), 400

    user_id = int(user_id)

    # If date not provided → use today
    if not date:
        date = datetime.utcnow().strftime("%Y-%m-%d")

    logs = list(pages_collection.find(
        {
            "userId": user_id,
            "createdAt": {"$regex": f"^{date}"}
        },
        {"_id": 0}
    ))

    if not logs:
        return jsonify({
            "userId": user_id,
            "date": date,
            "summary": "No activity logged for this date.",
            "updatedAt": datetime.utcnow().isoformat()
        }), 200

    combined_text = "\n".join(log["content"] for log in logs)

    try:
        summary_text = summarize_logs(combined_text)
    except Exception as e:
        print("❌ Summary AI error:", e)
        summary_text = "Summary is temporarily unavailable."

    return jsonify({
        "userId": user_id,
        "date": date,
        "summary": summary_text,
        "updatedAt": datetime.utcnow().isoformat()
    }), 200

# -----------------------------
# SEARCH / FILTER by tag
# -----------------------------
@app.route("/logs/filter", methods=["GET"])
def search_pages_by_tag():
    user_id = request.args.get("userId")
    tag = request.args.get("tag")

    pages = list(pages_collection.find(
        {"userId": int(user_id), "tags": tag},
        {"_id": 0}
    ))

    return jsonify({"entries": pages}), 200

# -----------------------------
# SEARCH by content keyword
# -----------------------------
@app.route("/logs/search", methods=["GET"])
def search_pages_by_content():
    user_id = request.args.get("userId")
    keyword = request.args.get("content")

    pages = list(pages_collection.find(
        {
            "userId": int(user_id),
            "content": {"$regex": keyword, "$options": "i"}
        },
        {"_id": 0}
    ))

    return jsonify({"entries": pages}), 200

# -----------------------------
# RUN SERVER
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
