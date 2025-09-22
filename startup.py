from app import app

if __name__ == "__main__":
    # Use 0.0.0.0 so Azure can reach it
    app.run(host='0.0.0.0', port=8000)
