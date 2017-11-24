import json

from flask import jsonify, abort, make_response
from postgresql_db.models import *
from services import nlpService, fileService
from services.staticStrings import *

from app import db

########################
# Conversation Handling
########################

"""
Returns a json representation of the Conversation
conversation_id: ID of the conversation
:return JSON representation of the conversation
"""


def get_conversation(conversation_id):
    conversation = __get_conversation(conversation_id)

    return ConversationSchema().jsonify(conversation)


"""
Initializes a new Conversation
name: Person's name
person_type: Either LANDLORD or TENANT
:return JSON with id of newly created Conversation
"""


def init_conversation(name, person_type):
    if person_type.upper() not in PersonType.__members__:
        return abort(make_response(jsonify(message="Invalid person type provided"), 400))

    conversation = Conversation(name=name, person_type=PersonType[person_type.upper()])

    # Persist new conversation to DB
    db.session.add(conversation)
    db.session.commit()

    return jsonify(
        {
            'conversation_id': conversation.id
        }
    )


"""
Process an incoming message from the user
conversation_id: ID of the conversation
:return JSON object with data for the front end, including response text and file requests.
"""


def receive_message(conversation_id, message):
    conversation = __get_conversation(conversation_id)

    response_text = None
    response_html = None
    file_request = None
    possible_answers = None
    additional_info = None
    enforce_possible_answer = False

    user_message = None

    # First message in the conversation
    if len(conversation.messages) == 0:
        response_html = StaticStrings.chooseFrom(StaticStrings.disclaimer).format(name=conversation.name)
        possible_answers = json.dumps(["Yes"])
        enforce_possible_answer = True
    else:
        # Add user's message
        user_message = Message(sender_type=SenderType.USER, text=message, relevant_fact=conversation.current_fact)
        conversation.messages.append(user_message)

        # Commit user's message
        db.session.commit()

        # Generate response text & optional parameters
        response = __generate_response(conversation, user_message.text)
        response_text = response.get('response_text')
        file_request = response.get('file_request')
        possible_answers = response.get('possible_answers')

    # Persist response message
    if response_text is not None:
        response = Message(
            sender_type=SenderType.BOT,
            text=response_text,
            possible_answers=possible_answers,
            enforce_possible_answer=enforce_possible_answer,
            relevant_fact=conversation.current_fact
        )
    elif response_html is not None:
        response = Message(
            sender_type=SenderType.BOT,
            text=response_html,
            possible_answers=possible_answers,
            enforce_possible_answer=enforce_possible_answer,
            relevant_fact=conversation.current_fact
        )
    else:
        return abort(make_response(jsonify(message="Response text not generated"), 400))

    # Create relationship between message and file request if present
    if file_request is not None:
        response.file_request = file_request

    conversation.messages.append(response)

    # Commit bot's message
    db.session.commit()

    # Build response dict
    response_dict = {'conversation_id': conversation.id}

    if response_text is not None:
        response_dict['message'] = response_text
    if response_html is not None:
        response_dict['html'] = response_html
    if file_request is not None:
        response_dict['file_request'] = FileRequestSchema().dump(file_request).data
    if possible_answers is not None:
        response_dict['possible_answers'] = possible_answers
        if enforce_possible_answer:
            response_dict['enforce_possible_answer'] = True

    # Get the last extracted fact entity
    if len(conversation.fact_entities) > 0 and conversation.fact_entities[-1]:
        fact_entity_value = conversation.fact_entities[-1].value

        # Get the last fact name
        if user_message and user_message.relevant_fact:
            fact_name = user_message.relevant_fact.name

            if 'message' in response_dict:
                key = 'message'
            if 'html' in response_dict:
                key = 'html'

            # Format new bot response with prediction information
            response_dict[key] = "Prediction: " + fact_name + '=' + fact_entity_value + \
                    '<br/><br/>' + "Next question: " + response_dict[key]


    return jsonify(response_dict)

"""
Stores the user's feedback as to whether our NLP prediction/classification/extraction is correct
conversation_id: ID of the conversation
conversation_id: The message provided by the user as confirmation (True/False/'$500', etc)
:return 200 response once the confirmation is persisted
"""

def store_user_confirmation(conversation_id, confirmation):
    conversation = __get_conversation(conversation_id)
    messages = conversation.messages[::-1]
    for message in messages:
        if message.sender_type == SenderType.USER:
            user_message = message

    user_confirmation = UserConfirmation(
        fact_id=conversation.current_fact.id,
        message_id=user_message.id,
        text=confirmation
    )

    # Persist new user confirmation to DB
    db.session.add(user_confirmation)
    db.session.commit()

    return jsonify({'message': 'User confirmation stored successfully'})


################
# File Handling
################

"""
Retrieves a list of data about files the user has uploaded
conversation_id: ID of the conversation
:return JSON object with file data
"""


def get_file_list(conversation_id):
    conversation = __get_conversation(conversation_id)

    return jsonify(
        {
            'files': [FileSchema().dump(file).data for file in conversation.files]
        }
    )


"""
Uploads a file and creates a database entry for the File linked to the Conversation
conversation_id: ID of the conversation
file: Werkzeug file data received from front end
:return JSON object with file data
"""


def upload_file(conversation_id, file):
    conversation = __get_conversation(conversation_id)

    # Check if the file has a filename
    if file.filename == '':
        abort(make_response(jsonify(message="No file selected"), 400))

    if fileService.is_accepted_format(file):
        # Create the file and commit it to generate id
        new_file = File(name=fileService.sanitize_name(file), type=file.content_type)
        conversation.files.append(new_file)
        db.session.commit()

        # Generate path information and upload file to disk
        new_file.path = fileService.generate_path(conversation.id, new_file.id)
        fileService.upload_file(file, new_file.path, new_file.name)
        db.session.commit()

        # Return the file info
        return FileSchema().jsonify(new_file)
    else:
        abort(make_response(
            jsonify(message="Filetype {} is not supported. Supported filetypes are {}.".format(
                fileService.get_file_extension(file), fileService.get_accepted_formats_string())), 400))


##################
# Private Methods
##################

"""
Retrieves the conversation by id, returning 404 if not found.
conversation_id: ID of the conversation
:return Conversaion if exists, else aborts with 404
"""


def __get_conversation(conversation_id):
    conversation = db.session.query(Conversation).get(conversation_id)

    if conversation:
        return conversation

    abort(make_response(jsonify(message="Conversation does not exist"), 404))


"""
Generates the next response for the bot, based on conversation's state
conversation: Conversation
message: User's message
:return Next response for bot
"""


def __generate_response(conversation, message):
    if __has_just_accepted_disclaimer(conversation):
        return __ask_initial_question(conversation)
    elif conversation.claim_category is None:
        nlp_request = nlpService.claim_category(conversation.id, message)

        # Refresh the session, since nlpService may have modified conversation
        db.session.refresh(conversation)

        return {'response_text': nlp_request['message']}
    elif conversation.current_fact is not None:
        nlp_request = nlpService.submit_message(conversation.id, message)

        # Refresh the session, since nlpService may have modified conversation
        db.session.refresh(conversation)

        return {'response_text': nlp_request['message']}


"""
Returns the initial question to ask, and optionally a file request
conversation: Conversation
:return Next response for bot
"""


def __ask_initial_question(conversation):
    person_type = conversation.person_type

    file_request = None
    if person_type is PersonType.TENANT:
        file_request = FileRequest(document_type=DocumentType.LEASE)

    db.session.commit()

    # Generate response based on person type
    response = None
    if person_type is PersonType.TENANT:
        response = StaticStrings.chooseFrom(StaticStrings.problem_inquiry_tenant).format(name=conversation.name)
    elif person_type is PersonType.LANDLORD:
        response = StaticStrings.chooseFrom(StaticStrings.problem_inquiry_landlord).format(name=conversation.name)

    return {'response_text': response, 'file_request': file_request}


def __has_just_accepted_disclaimer(conversation):
    return len(conversation.messages) == 2

