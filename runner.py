

from webhook_server import app
from config import PORT

if __name__ == '__main__':
    print(f"🚀 Starting News Bot on port {PORT}...")
    app.run(host='0.0.0.0', port=int(PORT), debug=False, use_reloader=False)
