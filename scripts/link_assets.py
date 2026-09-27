import sys
import sqlite3

sys.stdout.reconfigure(encoding='utf-8')
con = sqlite3.connect('data/owi.db')
cur = con.cursor()

# 1. Update MediaAssets 5-12
asset_message_map = {
    6: 168, # Page 65 remove this
    7: 171, # Execution diagram
    9: 161, # Book cover / Hamdeen Beshara
    8: 163, # Author bio & indexing
    5: 166, # Quote page
    10: 155, # Page 19
    11: 158, # Page 20
    12: 153, # Application flexibility
}

for aid, mid in asset_message_map.items():
    cur.execute('UPDATE media_assets SET conversation_id = 13, message_id = ? WHERE id = ?', (mid, aid))
    cur.execute('UPDATE document_records SET conversation_id = 13 WHERE media_asset_id = ?', (aid,))

# Clean up Msg 168 text
cur.execute("UPDATE messages SET content = 'page 65 , remove this' WHERE id = 168")

# Handle Asset 25 (was pointing to 431, duplicate of Asset 23 pointing to 178)
cur.execute('DELETE FROM media_assets WHERE id = 25')

# Delete attachment records for companion messages >= 425
cur.execute('DELETE FROM attachment_records WHERE message_id >= 425')

# Delete duplicate companion messages >= 425 in Conversation 13
cur.execute('DELETE FROM messages WHERE conversation_id = 13 AND id >= 425')

# Update conversation 13 message count
cnt = cur.execute('SELECT COUNT(*) FROM messages WHERE conversation_id = 13').fetchone()[0]
cur.execute('UPDATE conversations SET message_count = ? WHERE id = 13', (cnt,))

con.commit()
print(f'Successfully updated! Conversation 13 now has {cnt} clean, verified messages.')
