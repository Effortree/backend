from flask import Flask, request, jsonify
from models.quest import quests_collection  # import the collection

app = Flask(__name__)

# Define your "Secret Key" (In real apps, this is hidden in an .env file)
SECRET_TOKEN = "effortree-secret-123"

@app.route("/quests", methods=["POST"])
def create_quest():
    # --- PART 1: CHECK THE SECRET TOKEN (Authorization) ---
    # Look for the 'Authorization' header in Postman
    auth_header = request.headers.get("Authorization")
    
    # If the token is missing or wrong, return the 403 error from your screenshot
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({
            "code": 10306,
            "message": "You do not have permission to access users.",
            "detail": "This function is only accessible to admins."
        }), 403  # This matches your screenshot's error message!

    # --- PART 2: LINK TO USER ---
    data = request.get_json()
    
    # Check if a nickname was provided in the JSON body
    if "nickname" not in data:
        return jsonify({"error": "A nickname is required to link this quest to a user"}), 400

    # Insert the data (which now includes the nickname) into MongoDB
    quests_collection.insert_one(data)
    
    return jsonify({
        "message": f"Quest added and linked to {data['nickname']}!",
        "status": "success"
    }), 201

# READ all quests
@app.route("/quests", methods=["GET"])
def get_quests():
    quests = list(quests_collection.find({}, {"_id": 0}))
    return jsonify(quests)

# UPDATE a quest (PATCH)
@app.route("/quests", methods=["PATCH"])
def update_quest():
    auth_header = request.headers.get("Authorization")
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"message": "Forbidden"}), 403

    data = request.get_json()
    title = data.get("title") # We find the quest by its title
    
    # Update the description and difficulty in MongoDB
    quests_collection.update_one(
        {"title": title}, 
        {"$set": {"description": data.get("description"), "difficulty": data.get("difficulty")}}
    )
    return jsonify({"message": "Quest updated successfully!"})

# DELETE a quest
@app.route("/quests", methods=["DELETE"])
def delete_quest():
    auth_header = request.headers.get("Authorization")
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"message": "Forbidden"}), 403

    data = request.get_json()
    title = data.get("title")
    
    quests_collection.delete_one({"title": title})
    return jsonify({"message": "Quest deleted successfully!"})

# --- USER ROUTES ---

# CREATE a new user (nickname, birthdate, gender)
@app.route("/users", methods=["POST"])
def create_user():
    data = request.get_json()
    # Matches your requirement: nickname, birthdate, gender
    from models.quest import users_collection 
    users_collection.insert_one(data)
    return jsonify({"message": "User profile created!"}), 201

# READ all users (The list of "Minsu", "Aiperi", etc.)
@app.route("/users", methods=["GET"])
def get_users():
    from models.quest import users_collection
    users = list(users_collection.find({}, {"_id": 0}))
    return jsonify(users)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)  # 0.0.0.0 = public access
