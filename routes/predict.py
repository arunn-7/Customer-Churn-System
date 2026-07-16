from flask import Blueprint, request, jsonify
from ml.predict import predict_customer

predict_bp = Blueprint("predict", __name__)

@predict_bp.route("/predict", methods=["POST"])
def predict():

    data = request.json

    result = predict_customer(data)

    return jsonify(result)
    