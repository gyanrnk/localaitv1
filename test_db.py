# import db

# db.execute("INSERT INTO item_events (event, at) VALUES (%s, %s)", ('test_connection', '2026-05-07'))
# rows = db.fetchall("SELECT * FROM item_events WHERE event='test_connection'")
# print('CloudSQL working:', len(rows) > 0)
# print('Rows found:', len(rows))


# import db
# rows = db.fetchall("SELECT * FROM information_schema.columns WHERE table_name='news_items' ORDER BY ordinal_position")
# for r in rows: print(r['column_name'])


# import db
# rows = db.fetchall("SELECT indexname, indexdef FROM pg_indexes WHERE tablename='news_items'")
# for r in rows: print(r['indexname'], '|', r['indexdef'])



# from bulletin_builder import append_news_item
# from datetime import datetime
# append_news_item({
#     'counter': 9999,
#     'media_type': 'image',
#     'priority': 'normal',
#     'sender_name': 'Test',
#     'sender_photo': '',
#     'sender_gif': '',
#     'timestamp': datetime.now().isoformat(),
#     'headline': 'Test Headline',
#     'script_filename': '',
#     'headline_filename': '',
#     'headline_audio': 'test.mp3',
#     'script_audio': 'test.mp3',
#     'script_duration': 10.0,
#     'headline_duration': 3.0,
#     'total_duration': 13.0,
#     'clip_structure': None,
#     'clip_start': None,
#     'clip_end': None,
#     'clip_video_path': None,
#     'multi_image_paths': [],
#     'multi_video_paths': [],
#     'intro_audio_filename': None,
#     'analysis_audio_filename': None,
#     'status': 'complete',
#     'original_text': 'test',
#     'location_id': 0,
#     'location_name': 'Test',
#     'location_address': '',
#     'created_at': datetime.now().isoformat(),
#     'category_id': 1,
#     'user_id': '',
# })



import db
rows = db.fetchall('SELECT counter, headline FROM news_items ORDER BY id DESC LIMIT 5')
print(rows)



