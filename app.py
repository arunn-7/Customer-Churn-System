from flask import Flask
from config import Config
from database.db import db
from models.customer import Customer
from routes.predict import predict_bp

app = Flask(__name__)

app.config.from_object(Config)

db.init_app(app)

# Register Blueprint
app.register_blueprint(predict_bp)

@app.route("/")
def home():
    return "Customer Churn Prediction System Backend is Running!"

@app.route("/test-db")
def test_db():
    try:
        db.engine.connect()
        return "✅ Database Connected Successfully!"
    except Exception as e:
        return f"❌ Database Connection Failed: {str(e)}"

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True)