# Changelog

## 3.0.0

- Now **Photo Hub**: Photo Shuffle and Photo Puller combined into one add-on with one web UI (Folders and Unsplash tabs)
- Unsplash collections publish their photos to **MQTT** as image entities, like folder shuffles do. The separate Photo Puller integration is no longer needed, and nothing is written to `/share` any more
- Unsplash entities keep the IDs the Photo Puller integration used (`image.<name>_photos_landscape` / `_portrait`) and the `photographer`, `photo_url` and `search_term` attributes. They live on one "Unsplash Photos" device
- Unsplash photos are resized and re-encoded with the same `max_dimension` and `jpeg_quality` settings as folder photos
- Unsplash collections are now added, edited and deleted one at a time (no "Save changes" step), and the Unsplash tab shows requests per hour, a countdown to the next refresh and photographer credits
- The refresh schedule survives restarts, so restarting no longer spends Unsplash requests
- New options: `unsplash_access_key`, `unsplash_interval_minutes`, `unsplash_image_size`
- Folder shuffles, entity IDs and the slug (`photo_shuffle`) are unchanged, so existing shuffles carry over
- The `photo_puller_updated` and `photo_puller_collections_changed` events are gone. Trigger on the image entity instead

Upgrading from Photo Puller: re-add your collections in the Unsplash tab, and remove the old integration first. See the Documentation tab.

## 2.1.1

- Fix: shuffles created by earlier versions stayed on their own device and the shared "Photo Shuffle" device stayed empty. The add-on re-creates each entity once on the shared device. Entity IDs are unchanged

## 2.1.0

- All shuffle image entities live under ONE device called "Photo Shuffle"
- Removed the MQTT "Next photo" button. Use the Next button in the web UI

## 2.0.0

- New web UI (sidebar panel) to add, edit, pause and delete shuffles, with live previews and an activity log
- Folder browser limited to the paths you allow
- Shuffles are stored by the add-on and survive restarts and updates

Earlier versions: see the Photo Shuffle repository history.
