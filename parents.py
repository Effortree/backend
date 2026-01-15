# parents.py
from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from collections import defaultdict
from models.quest import quests_collection, gifts_collection, users_collection, links_collection
from parents_llm import run_parent_interpretation
from pymongo import ReturnDocument
import oci
import config
from PIL import Image
import io

parents_bp = Blueprint("parents", __name__)

ROLLING_DAYS = 14

# ------------------------------
# RESIZE Image
# ------------------------------
def resize_image(file, max_size=1024):
    img = Image.open(file)
    img.thumbnail((max_size, max_size))  # maintain aspect ratio
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG', quality=85)
    img_byte_arr.seek(0)
    return img_byte_arr

# -----------------------------
# INTERNAL: extract signals (qualitative only)
# -----------------------------
def extract_parent_signals(child_id):
    today = datetime.utcnow().date()
    start = today - timedelta(days=ROLLING_DAYS)

    quests = list(quests_collection.find({"userId": child_id}))

    active_days = set()
    has_any_activity = False

    for q in quests:
        for log in q.get("spent_logs", []):
            d = datetime.strptime(log["spent_at"], "%Y-%m-%d").date()
            if start <= d <= today and log["spent_minutes"] > 0:
                active_days.add(d)
                has_any_activity = True

    # qualitative interpretation
    if not has_any_activity:
        return {"engagement_flow": "paused", "direction": "unclear", "guidance_level": "wait"}
    if len(active_days) >= 8:
        return {"engagement_flow": "steady", "direction": "stable", "guidance_level": "wait"}
    if 3 <= len(active_days) < 8:
        return {"engagement_flow": "uneven", "direction": "recovering", "guidance_level": "gentle_support"}
    return {"engagement_flow": "slowing", "direction": "slowing", "guidance_level": "attention"}

# -----------------------------
# INTERNAL: build narrative features
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
    child_id = request.args.get("childId")
    if not child_id:
        return jsonify({"error": "childId is required"}), 400

    child_id = int(child_id)
    signals = extract_parent_signals(child_id)
    narrative = build_narrative_features(signals)
    interpretation = run_parent_interpretation(narrative)

    return jsonify({
        "current_guidance": interpretation.get("current_guidance", "No interpretation available."),
        "interpretation_rationale": "Analysis based on 14-day rolling activity patterns."
    }), 200

# -----------------------------
# PARENT CHAT (interpretation only)
# -----------------------------
@parents_bp.route("/parents/chat", methods=["POST"])
def parent_chat():
    data = request.json
    child_id = data.get("childId")
    question = data.get("question")
    if not child_id or not question:
        return jsonify({"error": "childId and question are required"}), 400

    child_id = int(child_id)
    signals = extract_parent_signals(child_id)
    narrative_features = build_narrative_features(signals)

    if not narrative_features:
        narrative_features = ["No recent activity has been recorded; interpretation is based on usual patterns."]

    answer = run_parent_interpretation(narrative_features, question=question)

    return jsonify({
        "answer": answer.get("answer"),
        "disclaimer": "I can't share specific activity details. My role is to explain overall interpretation rather than provide raw data."
    }), 200

# -----------------------------
# OCI Setup for gift images
# -----------------------------
signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
object_storage = oci.object_storage.ObjectStorageClient({}, signer=signer)
namespace = config.OCI_NAMESPACE
bucket_name = "effortree-bucket"

# -----------------------------
# CREATE / UPDATE GIFT
# -----------------------------
@parents_bp.route("/parents/gift", methods=["POST"])
def create_or_update_gift():
    child_id = request.form.get("childId")
    message = request.form.get("message")
    image_file = request.files.get("giftImage")

    if not child_id or not message:
        return jsonify({"error": "Missing childId or message"}), 400

    image_url = None
    if image_file:
        filename = f"gift_{child_id}_{datetime.utcnow().timestamp()}.jpg"
        image_bytes = resize_image(image_file, max_size=1024)
        object_storage.put_object(namespace, bucket_name, filename, image_bytes.read())
        image_url = f"https://objectstorage.{config.OCI_REGION}.oraclecloud.com/n/{namespace}/b/{bucket_name}/o/{filename}"

    gifts_collection.find_one_and_update(
        {"childUserId": int(child_id)},
        {"$set": {"message": message, "imageUrl": image_url, "updated_at": datetime.utcnow().isoformat() + "Z"}},
        upsert=True
    )

    return jsonify({"status": "saved", "imageUrl": image_url}), 200

# -----------------------------
# GET GIFT
# -----------------------------
@parents_bp.route("/parents/gift", methods=["GET"])
def get_gift():
    child_id = request.args.get("childId")
    if not child_id:
        return jsonify({"error": "childId is required"}), 400

    gift = gifts_collection.find_one({"childUserId": int(child_id)})
    if not gift:
        return jsonify({"error": "No gift found for this child."}), 404

    return jsonify({
        "childId": gift["childUserId"],
        "message": gift.get("message"),
        "imageUrl": gift.get("imageUrl"),
        "updated_at": gift.get("updated_at")
    }), 200

# -----------------------------
# DELETE GIFT
# -----------------------------
@parents_bp.route("/parents/gift", methods=["DELETE"])
def delete_gift():
    data = request.json
    child_id = data.get("childId")
    if not child_id:
        return jsonify({"error": "childId is required"}), 400

    result = gifts_collection.delete_one({"childUserId": int(child_id)})
    if result.deleted_count == 0:
        return jsonify({"error": "No gift found to delete."}), 404

    return jsonify({"status": "deleted"}), 200

# -----------------------------
# CONNECT PARENT TO CHILD
# -----------------------------
@parents_bp.route("/parents/connect", methods=["POST"])
def connect_child():
    data = request.get_json()
    child_id = data.get("childId")
    parent_email = data.get("connectToEmail")

    if not child_id or not parent_email:
        return jsonify({"error": "childId and connectToEmail are required"}), 400

    # Validate child exists
    child = users_collection.find_one({"userId": int(child_id)}, {"_id": 0, "userId": 1})
    if not child:
        return jsonify({"error": "Child not found"}), 404

    # Find parent by email
    parent = users_collection.find_one({"email": parent_email}, {"_id": 0, "userId": 1, "role": 1})
    if not parent:
        return jsonify({"error": "Parent not found"}), 404

    if parent["role"] != "parent":
        return jsonify({"error": "Target user is not a parent"}), 400

    now = datetime.utcnow().isoformat() + "Z"

    # Upsert parent-child link
    links_collection.find_one_and_update(
        {"parentId": parent["userId"]},
        {"$addToSet": {"childIds": int(child_id)},
         "$setOnInsert": {"created_at": now},
         "$set": {"updated_at": now}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )

    return jsonify({"childId": int(child_id), "parentId": parent["userId"]}), 200
