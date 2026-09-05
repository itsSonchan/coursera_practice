"""
CodeCraftHub - Course Tracking REST API

This Flask application provides CRUD operations for courses and stores
course data in a local JSON file named courses.json.

Run with:

    python app.py
"""

from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
import json
import os
import tempfile

from flask import Flask, jsonify, request


# Create the Flask application
app = Flask(__name__)


# Store courses.json in the same directory as this app.py file
DATA_FILE = Path(__file__).parent / "courses.json"


# A lock prevents two requests from writing to the JSON file at the same time
file_lock = Lock()


# These are the only valid course status values
VALID_STATUSES = {
    "Not Started",
    "In Progress",
    "Completed",
}


class CourseFileError(Exception):
    """Raised when there is a problem reading or writing courses.json."""


def create_data_file_if_missing():
    """
    Create courses.json automatically if it does not already exist.

    The file starts with an empty JSON list because courses are stored
    as a list of objects.
    """
    try:
        if not DATA_FILE.exists():
            with DATA_FILE.open("w", encoding="utf-8") as file:
                json.dump([], file, indent=4)
                file.write("\n")
    except OSError as error:
        raise CourseFileError(
            f"Could not create data file: {error}"
        ) from error


def load_courses():
    """
    Read and return all courses from courses.json.

    Returns:
        list: A list of course dictionaries.

    Raises:
        CourseFileError: If the file cannot be read or contains invalid JSON.
    """
    create_data_file_if_missing()

    try:
        with file_lock:
            with DATA_FILE.open("r", encoding="utf-8") as file:
                courses = json.load(file)

        # The JSON file should contain a list of courses
        if not isinstance(courses, list):
            raise CourseFileError(
                "courses.json must contain a JSON list."
            )

        return courses

    except json.JSONDecodeError as error:
        raise CourseFileError(
            "courses.json contains invalid JSON."
        ) from error

    except OSError as error:
        raise CourseFileError(
            f"Could not read courses.json: {error}"
        ) from error


def save_courses(courses):
    """
    Save all courses to courses.json.

    A temporary file is used first. Once writing succeeds, it replaces
    the original file. This helps reduce the chance of leaving a
    partially written JSON file.
    """
    try:
        with file_lock:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                delete=False,
                dir=DATA_FILE.parent,
                suffix=".tmp",
            ) as temporary_file:
                json.dump(courses, temporary_file, indent=4)
                temporary_file.write("\n")
                temporary_file_path = temporary_file.name

            # Replace the original file with the completed temporary file
            os.replace(temporary_file_path, DATA_FILE)

    except OSError as error:
        # Try to remove the temporary file if something went wrong
        if "temporary_file_path" in locals():
            try:
                Path(temporary_file_path).unlink(missing_ok=True)
            except OSError:
                pass

        raise CourseFileError(
            f"Could not write to courses.json: {error}"
        ) from error


def get_next_course_id(courses):
    """
    Generate the next numeric course ID.

    IDs start at 1. The next ID is one higher than the current
    highest ID in the file.
    """
    if not courses:
        return 1

    existing_ids = []

    for course in courses:
        course_id = course.get("id")

        # Only consider integer IDs when finding the highest ID
        if isinstance(course_id, int):
            existing_ids.append(course_id)

    if not existing_ids:
        return 1

    return max(existing_ids) + 1


def get_request_data():
    """
    Read JSON data from the request body.

    Returns:
        dict: The submitted JSON data.

    Returns an error response if the body is missing or invalid.
    """
    data = request.get_json(silent=True)

    if data is None:
        return None, jsonify({
            "error": "Request body must contain valid JSON."
        }), 400

    if not isinstance(data, dict):
        return None, jsonify({
            "error": "Request body must be a JSON object."
        }), 400

    return data, None, None


def validate_course_data(data):
    """
    Validate the fields required to create or update a course.

    Returns:
        str or None: An error message if validation fails,
        otherwise None.
    """
    required_fields = [
        "name",
        "description",
        "target_date",
        "status",
    ]

    # Check that every required field exists
    missing_fields = [
        field for field in required_fields
        if field not in data
    ]

    if missing_fields:
        return (
            "Missing required field(s): "
            + ", ".join(missing_fields)
        )

    # Name must be a non-empty string
    if not isinstance(data["name"], str) or not data["name"].strip():
        return "name must be a non-empty string."

    # Description must be a non-empty string
    if (
        not isinstance(data["description"], str)
        or not data["description"].strip()
    ):
        return "description must be a non-empty string."

    # Validate the target date format and ensure it is a real date
    if not isinstance(data["target_date"], str):
        return "target_date must be a string in YYYY-MM-DD format."

    try:
        datetime.strptime(data["target_date"], "%Y-%m-%d")
    except ValueError:
        return "target_date must use the format YYYY-MM-DD."

    # Validate the status value
    if data["status"] not in VALID_STATUSES:
        return (
            "status must be one of: "
            + ", ".join(sorted(VALID_STATUSES))
        )

    return None


def find_course(courses, course_id):
    """
    Find one course by its numeric ID.

    Returns:
        dict or None: The matching course, if found.
    """
    for course in courses:
        if course.get("id") == course_id:
            return course

    return None


@app.route("/api/courses", methods=["POST"])
def create_course():
    """
    Add a new course.

    POST /api/courses
    """
    data, error_response, status_code = get_request_data()

    if error_response:
        return error_response, status_code

    validation_error = validate_course_data(data)

    if validation_error:
        return jsonify({
            "error": validation_error
        }), 400

    try:
        courses = load_courses()

        new_course = {
            "id": get_next_course_id(courses),
            "name": data["name"].strip(),
            "description": data["description"].strip(),
            "target_date": data["target_date"],
            "status": data["status"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        courses.append(new_course)
        save_courses(courses)

        return jsonify(new_course), 201

    except CourseFileError as error:
        return jsonify({
            "error": str(error)
        }), 500


@app.route("/api/courses", methods=["GET"])
def get_all_courses():
    """
    Return all courses.

    GET /api/courses
    """
    try:
        courses = load_courses()

        return jsonify({
            "courses": courses,
            "count": len(courses),
        }), 200

    except CourseFileError as error:
        return jsonify({
            "error": str(error)
        }), 500


@app.route("/api/courses/<int:course_id>", methods=["GET"])
def get_specific_course(course_id):
    """
    Return one course by ID.

    GET /api/courses/<course_id>
    """
    try:
        courses = load_courses()
        course = find_course(courses, course_id)

        if course is None:
            return jsonify({
                "error": f"Course with ID {course_id} was not found."
            }), 404

        return jsonify(course), 200

    except CourseFileError as error:
        return jsonify({
            "error": str(error)
        }), 500


@app.route("/api/courses/<int:course_id>", methods=["PUT"])
def update_course(course_id):
    """
    Replace all editable fields for an existing course.

    PUT /api/courses/<course_id>

    The ID and created_at values are preserved automatically.
    """
    data, error_response, status_code = get_request_data()

    if error_response:
        return error_response, status_code

    validation_error = validate_course_data(data)

    if validation_error:
        return jsonify({
            "error": validation_error
        }), 400

    try:
        courses = load_courses()
        course = find_course(courses, course_id)

        if course is None:
            return jsonify({
                "error": f"Course with ID {course_id} was not found."
            }), 404

        # Update only the editable fields
        course["name"] = data["name"].strip()
        course["description"] = data["description"].strip()
        course["target_date"] = data["target_date"]
        course["status"] = data["status"]

        save_courses(courses)

        return jsonify(course), 200

    except CourseFileError as error:
        return jsonify({
            "error": str(error)
        }), 500


@app.route("/api/courses/<int:course_id>", methods=["DELETE"])
def delete_course(course_id):
    """
    Delete a course by ID.

    DELETE /api/courses/<course_id>
    """
    try:
        courses = load_courses()
        course = find_course(courses, course_id)

        if course is None:
            return jsonify({
                "error": f"Course with ID {course_id} was not found."
            }), 404

        # Remove the matching course from the list
        courses.remove(course)
        save_courses(courses)

        return jsonify({
            "message": f"Course with ID {course_id} was deleted successfully."
        }), 200

    except CourseFileError as error:
        return jsonify({
            "error": str(error)
        }), 500


@app.errorhandler(404)
def handle_not_found(error):
    """
    Handle unknown URLs.

    This is separate from the course-not-found responses above because
    it handles routes that do not exist at all.
    """
    return jsonify({
        "error": "The requested endpoint was not found."
    }), 404


@app.errorhandler(405)
def handle_method_not_allowed(error):
    """Handle requests that use an unsupported HTTP method."""
    return jsonify({
        "error": "The HTTP method is not allowed for this endpoint."
    }), 405


@app.errorhandler(500)
def handle_internal_server_error(error):
    """Return JSON instead of Flask's default HTML error page."""
    return jsonify({
        "error": "An unexpected internal server error occurred."
    }), 500


if __name__ == "__main__":
    # Make sure courses.json exists before starting the server
    try:
        create_data_file_if_missing()
        print(f"Using course data file: {DATA_FILE}")
    except CourseFileError as error:
        print(f"Startup error: {error}")
        raise SystemExit(1)

    # debug=True is useful while learning and developing locally
    app.run(debug=True)