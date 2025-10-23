#!/usr/bin/env python3
"""
Local GitPhish server startup script
Starts the server on port 8081 for local development
"""

import sys
import os

# Add the project root to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# Set environment variable for Python path
os.environ['PYTHONPATH'] = project_root

try:
    from gitphish.core.gui.server import GitPhishGuiServer
    
    print("🚀 Starting GitPhish GUI Server on localhost:8081")
    print("📝 CSV scheduled campaigns feature is available!")
    print("🌐 Access at: http://localhost:8081")
    print("⏹️  Press Ctrl+C to stop\n")
    
    # Create and start server on port 8081
    server = GitPhishGuiServer(host='127.0.0.1', port=8081)
    server.run(debug=True)
    
except KeyboardInterrupt:
    print("\n👋 Server stopped by user")
    sys.exit(0)
except ImportError as e:
    print(f"❌ Missing dependency: {e}")
    print("💡 Try installing dependencies:")
    print("   pip install flask flask-cors boto3 twilio schedule sqlalchemy")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error starting server: {e}")
    sys.exit(1)