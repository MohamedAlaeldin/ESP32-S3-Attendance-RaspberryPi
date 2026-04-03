# known_faces/

Place student face photos in this folder.

## Naming Convention

Each photo **must** be named using the student's ID number:

```
202010374.jpg
202010375.jpg
202010376.jpg
...
```

The filename (without extension) is used as the **Student ID** and looked up in `students.json` to find the full name.

## Supported Formats

- `.jpg` / `.jpeg`
- `.png`

## Tips for Best Results

- Use a clear, front-facing photo with good lighting.
- One face per photo (only the first detected face is used).
- Avoid sunglasses, heavy filters, or extreme angles.
- A photo taken with a phone camera at normal distance works well.

## Adding a New Student

1. Add the photo here: `known_faces/{student_id}.jpg`
2. Add the student entry in `students.json`:
   ```json
   "202010381": "New Student Full Name"
   ```
3. Restart `app.py` so the new face is loaded into memory.
