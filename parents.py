# parents.py
from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from collections import defaultdict
from models.quest import quests_collection, gifts_collection
from parents_llm import run_parent_interpretation
from pymongo import ReturnDocument
import oci
import config
import os
from PIL import Image
import io

parents_bp = Blueprint("parents", __name__)

iso = datetime.utcnow().isoformat() + "Z"

ROLLING_DAYS = 14

# ------------------------------
# RESIZE Img
# ------------------------------
def resize_image(file, max_size=1024):
    # Open uploaded file
    img = Image.open(file)
    img.thumbnail((max_size, max_size))  # resize while keeping aspect ratio

    # Save to bytes
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG', quality=85)  # JPEG + reasonable quality
    img_byte_arr.seek(0)
    return img_byte_arr

# -----------------------------
# INTERNAL: extract signals (NO NUMBERS RETURNED)
# -----------------------------
def extract_parent_signals(user_id):
    """
    Uses raw quest data internally.
    Returns qualitative signals ONLY.
    """
    today = datetime.utcnow().date()
    start = today - timedelta(days=ROLLING_DAYS)

    quests = list(quests_collection.find({"userId": user_id}))

    active_days = set()
    has_any_activity = False

    for q in quests:
        for log in q.get("spent_logs", []):
            d = datetime.strptime(log["spent_at"], "%Y-%m-%d").date()
            if start <= d <= today and log["spent_minutes"] > 0:
                active_days.add(d)
                has_any_activity = True

    # ---- qualitative interpretation ----
    if not has_any_activity:
        return {
            "engagement_flow": "paused",
            "direction": "unclear",
            "guidance_level": "wait"
        }

    if len(active_days) >= 8:
        return {
            "engagement_flow": "steady",
            "direction": "stable",
            "guidance_level": "wait"
        }

    if 3 <= len(active_days) < 8:
        return {
            "engagement_flow": "uneven",
            "direction": "recovering",
            "guidance_level": "gentle_support"
        }

    return {
        "engagement_flow": "slowing",
        "direction": "slowing",
        "guidance_level": "attention"
    }

# -----------------------------
# INTERNAL: narrative abstraction
# -----------------------------
def build_narrative_features(signals):
    features = []

    flow = signals["engagement_flow"]
    direction = signals["direction"]
    guidance = signals["guidance_level"]

    if flow == "steady":
        features.append("The recent period shows a generally steady flow of engagement")
    elif flow == "uneven":
        features.append("The recent period shows some variation rather than a consistent rhythm")
    elif flow == "slowing":
        features.append("The recent period suggests a gradual slowing of momentum")
    else:
        features.append("The recent period appears quieter than usual")

    if direction == "recovering":
        features.append("There are signs that momentum can return naturally")
    elif direction == "slowing":
        features.append("The change appears gradual rather than abrupt")
    else:
        features.append("No strong directional change stands out")

    features.append("Short pauses are treated as part of a normal learning process")

    if guidance == "gentle_support":
        features.append("A supportive and low-pressure approach is currently most effective")
    elif guidance == "attention":
        features.append("The current rhythm suggests a need for gentle reconnection")
    elif guidance == "wait":
        features.append("Providing space for the student's natural rhythm is advised")

    return features

# -----------------------------
# PARENT INTERPRETATION API
# -----------------------------
@parents_bp.route("/parents/interpretation", methods=["GET"])
def parent_interpretation():
    user_id = int(request.args.get("userId"))

    if not user_id:
        return jsonify({"error": "UserId is required"}), 400

    signals = extract_parent_signals(user_id)
    narrative = build_narrative_features(signals)

    # ---- LLM CALL (NO RAW DATA PASSED) ----
    interpretation = run_parent_interpretation(narrative)

    return jsonify({
        "current_guidance": interpretation["current_guidance"],
        "interpretation_rationale": interpretation["interpretation_rationale"]
    }), 200

# -----------------------------
# INTERPRETATION-ONLY PARENT CHAT
# -----------------------------
@parents_bp.route("/parents/chat", methods=["POST"])
def parent_chat():
    data = request.json
    user_id = data.get("userId")
    question = data.get("question")

    if not user_id or not question:
        return jsonify({"error": "userId and question are required"}), 400

    # Get signals and narrative features (qualitative only)
    signals = extract_parent_signals(user_id)
    narrative_features = build_narrative_features(signals)

    # fallback if empty
    if not narrative_features:
        narrative_features = ["No recent activity has been recorded; interpretation is based on usual patterns."]

    # Send narrative + question to LLM
    answer = run_parent_interpretation(narrative_features, question=question)

    return jsonify({
        "answer": answer.get("answer"),
        "disclaimer": "I can't share specific activity details. My role is to explain overall interpretation rather than provide raw data."
    }), 200

# --- OCI Setup ---
# Keyless connection using the server's own identity
if os.getenv("RUNNING_ON_SERVER") == "true":

    # Use Keyless on the Ubuntu Server
    signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    object_storage = oci.object_storage.ObjectStorageClient({}, signer=signer)
    
else:
    # Use the .pem file on your MacBook
    config_local = {

        "user": os.getenv("OCI_USER"),
        "key_file": os.getenv("KEY_FILE"),
        "fingerprint": os.getenv("OCI_FINGERPRINT"),
        "tenancy": os.getenv("OCI_TENANCY"),
        "region": os.getenv("OCI_REGION")

    }

    object_storage = oci.object_storage.ObjectStorageClient(config_local)

namespace = config.OCI_NAMESPACE
bucket_name = "effortree-bucket"

@parents_bp.route("/parents/gift", methods=["POST"])
def create_or_update_gift():
    # 1. Handle the Data
    user_id = request.form.get("userId")
    message = request.form.get("message")
    image_file = request.files.get("giftImage") # The image from the user

    if not user_id or not message:
        return jsonify({"error": "Missing data"}), 400

    image_url = None

    # 2. Upload to OCI if an image exists
    if image_file:
        filename = f"gift_{user_id}_{datetime.utcnow().timestamp()}.jpg"

        # Resize before uploading
        image_bytes = resize_image(image_file, max_size=1024)

        object_storage.put_object(
            namespace,
            bucket_name,
            filename,
            image_bytes.read()
        )
        
        # Construct the Public URL (If bucket visibility is set to Public)
        image_url = f"https://objectstorage.{config.OCI_REGION}.oraclecloud.com/n/{namespace}/b/{bucket_name}/o/{filename}"

    # 3. Update MongoDB (Save the message AND the image link)
    gifts_collection.find_one_and_update(
        {"childUserId": user_id},
        {
            "$set": {
                "message": message, 
                "imageUrl": image_url, # Link to Oracle Storage
                "updated_at": datetime.utcnow().isoformat() + "Z"
            }
        },
        upsert=True
    )

    return jsonify({"status": "saved", "imageUrl": image_url}), 200

@parents_bp.route("/parents/gift", methods=["GET"])
def get_gift():
    # 1. Get child userId from query parameters
    user_id = request.args.get("userId")
    if not user_id:
        return jsonify({"error": "userId is required"}), 400

    # 2. Look up the gift in MongoDB
    gift = gifts_collection.find_one({"childUserId": user_id})
    if not gift:
        return jsonify({"error": "No gift found for this child."}), 404

    # 3. Prepare response
    response = {
        "childUserId": gift["childUserId"],
        "message": gift.get("message"),
        "imageUrl": gift.get("imageUrl"),
        "updated_at": gift.get("updated_at")
    }

    return jsonify(response), 200


@parents_bp.route("/parents/gift", methods=["DELETE"])
def delete_gift():
    # 1. Get child userId from request JSON
    data = request.json
    user_id = data.get("userId")
    if not user_id:
        return jsonify({"error": "userId is required"}), 400

    # 2. Attempt to delete the gift from MongoDB
    result = gifts_collection.delete_one({"childUserId": user_id})
    if result.deleted_count == 0:
        return jsonify({"error": "No gift found to delete."}), 404

    # 3. Return success
    return jsonify({"status": "deleted"}), 200
