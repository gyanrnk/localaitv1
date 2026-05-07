

# from webhook_server import app
# from config import PORT

# if __name__ == '__main__':
#     print(f"🚀 Starting News Bot on port {PORT}...")
#     app.run(host='0.0.0.0', port=int(PORT), debug=False, use_reloader=False)



from ticker_overlay import add_ticker_overlay
r = add_ticker_overlay(
    r'outputs\bulletins\bul_gen_20260413_160128\bul_gen_20260413_160128.mp4',
    r'outputs\bulletins\bul_gen_20260413_160128\test_tickered.mp4'
)
print('Result:', r)