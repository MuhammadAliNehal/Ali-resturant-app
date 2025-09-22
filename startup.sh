#!/bin/bash

# Set the port to the Azure-provided PORT
export PORT=${PORT:-8000}

# Start the Flask app with Gunicorn
# app:app assumes your Flask app object is named 'app' inside app.py
gunicorn --bind 0.0.0.0:$PORT app:app
