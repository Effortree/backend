# parents.py
from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from collections import defaultdict
from models.quest import quests_collection, users_collection, links_collection
from parents_llm import run_parent_interpretation
from pymongo import ReturnDocument
import oci
import config
from PIL import Image
import io
import os
parents_bp = Blueprint("parents", __name__)

ROLLING_DAYS = 14

def get_clean_id(id_val):
    """Safely converts any input to an integer for MongoDB."""
    try:
        return int(float(id_val))
    except (ValueError, TypeError):
        return None
    
# ------------------------------
# RESIZE Image
# ------------------------------
def resize_image(file, max_size=1024):
    img = Image.open(file)

    # 🔑 FIX: convert RGBA / P to RGB
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    img.thumbnail((max_size, max_size))

    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="JPEG", quality=85)
    img_byte_arr.seek(0)

    return img_byte_arr

# -----------------------------
# INTERNAL: extract signals (qualitative only)
# -----------------------------
def extract_parent_signals(child_id):
    child_id = int(child_id)
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
        return {"engagement_flow": "quiet", "direction": "steady", "guidance_level": "encourage"}
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
        features.append("The student is currently in a quiet period, which can be a natural time for reflection and exploration.")
        features.append("Encouraging curiosity at their own pace is recommended.")

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
    child_id = get_clean_id(request.args.get("childId"))
    if not child_id:
        return jsonify({"error": "childId is required"}), 400

    child_id = int(child_id)
    signals = extract_parent_signals(child_id)
    narrative = build_narrative_features(signals)
    interpretation = run_parent_interpretation(narrative)
    
    return jsonify({
        "current_guidance": interpretation.get("current_guidance", "No interpretation available."),
        "interpretation_rationale": narrative
    }), 200

# -----------------------------
# PARENT CHAT (interpretation only)
# -----------------------------
@parents_bp.route("/parents/chat", methods=["POST"])
def parent_chat():
    data = request.json
    child_id = data.get("childId")
    question = data.get("question")
    child_id = int(child_id)
    if not child_id or not question:
        return jsonify({"error": "childId and question are required"}), 400

    signals = extract_parent_signals(child_id)
    narrative_features = build_narrative_features(signals)

    if not narrative_features:
        narrative_features = ["No recent activity has been recorded; interpretation is based on usual patterns."]

    answer = run_parent_interpretation(narrative_features, question=question)

    return jsonify({
        "answer": answer.get("answer")
    }), 200

# -----------------------------
# OCI Setup for gift images
# -----------------------------
# signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
# object_storage = oci.object_storage.ObjectStorageClient({}, signer=signer)
namespace = config.OCI_NAMESPACE
bucket_name = "effortree-bucket"

# Check if we are running in Docker/Linux or on a Mac
if os.getenv("RUNNING_ON_SERVER") == "true":
    # Use Keyless on the Ubuntu Server
    signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    object_storage = oci.object_storage.ObjectStorageClient({}, signer=signer)
else:
    # Use the .pem file on your MacBook
    # (Make sure these variables are in your local .env)
    config_local = {
        "user": os.getenv("OCI_USER"),
        "key_file": os.getenv("KEY_FILE"), 
        "fingerprint": os.getenv("OCI_FINGERPRINT"),
        "tenancy": os.getenv("OCI_TENANCY"),
        "region": os.getenv("OCI_REGION")
    }
    object_storage = oci.object_storage.ObjectStorageClient(config_local)

# -----------------------------
# CREATE / UPDATE GIFT
# -----------------------------
@parents_bp.route("/parents/gift", methods=["POST"])
def create_or_update_gift():
    parent_id = request.form["parentId"]
    child_id = request.form.get("childId")
    message = request.form.get("message")
    image_file = request.files.get("giftImage")

    if not child_id or not message:
        return jsonify({"error": "Missing childId or message"}), 400

    parent_id = int(parent_id)
    child_id = int(child_id)
    
    link = links_collection.find_one({
        "parentId": parent_id,
        "childIds": int(child_id)
    })
    
    if not link:
        return jsonify({"error": "Parent not connected to this child"}), 403
    if not child_id or not message:
        return jsonify({"error": "Missing childId or message"}), 400
    
    image_url = None
    if image_file:
        filename = f"gift_{child_id}_{datetime.utcnow().timestamp()}.jpg"
        image_bytes = resize_image(image_file, max_size=1024)
        object_storage.put_object(namespace, bucket_name, filename, image_bytes.read())
        image_url = f"https://objectstorage.{config.OCI_REGION}.oraclecloud.com/n/{namespace}/b/{bucket_name}/o/{filename}"

    users_collection.find_one_and_update(
        {"userId": int(child_id)},
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

    gift = users_collection.find_one({"userId": int(child_id)})
    if not gift:
        return jsonify({"error": "No gift found for this child."}), 404

    return jsonify({
        "childId": gift.get("childId") or gift.get("userId"),
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

    result = users_collection.delete_one({"userId": int(child_id)})
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

    return jsonify({"childId": int(child_id)}), 200

# -----------------------------
# GET ALL CHILDREN OF A PARENT
# -----------------------------
@parents_bp.route("/parents/children", methods=["GET"])
def get_parent_children():
    parent_id = get_clean_id(request.args.get("parentId"))
    if not parent_id:
        return jsonify({"error": "parentId is required"}), 400

    parent_id = int(parent_id)

    # 1. Find parent-child links
    link = links_collection.find_one(
        {"parentId": parent_id},
        {"_id": 0, "childIds": 1}
    )

    if not link or not link.get("childIds"):
        return jsonify({"children": []}), 200

    child_ids = link["childIds"]

    # 2. Fetch child user records
    children = list(
        users_collection.find(
            {"userId": {"$in": child_ids}},
            {
                "_id": 0,
                "userId": 1,
                "name": 1,
                "nickname": 1,
                "email": 1,
                "role": 1
            }
        )
    )

    return jsonify({
        "parentId": parent_id,
        "children": children
    }), 200
