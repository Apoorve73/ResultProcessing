#----------------------------------------------------------------------------#
# Imports
#----------------------------------------------------------------------------#
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file
from flask_celery import make_celery
# from werkzeug import secure_filename
from db import collection,courses_collection,course_information,merit,chance_memo_collection
from werkzeug.datastructures import FileStorage
import logging
# import the Pandas library
import pandas
from merit_class import Merit
from student_class import Students,Courses
from logging import Formatter, FileHandler
import os
import io
import datetime
from forms import AddStudents,AddBranchForm
now = datetime.datetime.now()
#----------------------------------------------------------------------------#
# App Config.
#----------------------------------------------------------------------------#

app = Flask(__name__)
app.config.from_object('config')
app.config['CELERY_BROKER_URL'] ='redis://localhost:6379/0'

celery = make_celery(app)

global course_id;


#----------------------------------------------------------------------------#
# Controllers.
#----------------------------------------------------------------------------#



@app.route('/')
def home():
    courses = course_information.find()
    return render_template('pages/placeholder.home.html',courses=courses)

# Add new course and students to it.
@app.route('/students/add',methods = ['GET', 'POST'])
def uploadStudents():
    form = AddStudents()
    if form.validate_on_submit():
        print('validate form')
        filename = form.file.data.filename
        form.file.data.save('uploads/'+f'{form.course_id.data}'+filename)
        course_id = form.course_id.data
        course_name = form.name.data
        no_of_choices = form.no_of_choices.data
        special_category = form.special_category.data

        student = Students(course_id,course_name,no_of_choices)
        student.add_students(filename)
        information = {
            'name':course_name,
            'course_id':int(course_id),
            'EB':special_category,
            'no_of_branches':no_of_choices,
            'year':'2020',
            'processed':False
        }
        course_information.insert_one(information)

        course = Courses(course_id)
        if form.special_category.data:
            course.setEBCategory()

        return render_template('pages/placeholder.home.html')

    return render_template('forms/addCourse.html',form=form)

# View the particular Course Page
@app.route('/students/view/<course_id>',methods=['GET','POST'])
def viewStudents(course_id):
    form = AddBranchForm()
    if form.validate_on_submit():
        name = form.name.data
        internal_seats = form.internal_seats.data
        external = form.external_seats.data
        special = form.extra_seats.data
        course = Courses(course_id)
        course.setEBCategory()
        course.addBranch(name,internal_seats,external,special)
    total = collection.count_documents({'course': course_id})
    internals = collection.count_documents({'$and': [{'course': course_id}, {'category': 'I'}]})
    externals = collection.count_documents({'$and': [{'course': course_id}, {'category': 'E'}]})
    record = course_information.find_one({'course_id':int(course_id)})
    courses = courses_collection.find({'course':course_id})
    courses_len = courses_collection.count_documents({'course':course_id})

    return render_template('pages/view_students.html',total=total,courses_len=courses_len,internals=internals,externals=externals,record=record,courses=courses,form=form,course_id=course_id)

@app.route('/chance_memo', methods=['GET','POST'])
def chance_memo_input(course_id):
    
    if request.method:
        global chance_memo;
        chance_memo = request.form.get('Chance_memo')
        chance_memo = int(chance_memo)
        if num >= 0:
            return redirect(url_for('viewStudents', course_id = int(course_id)))
        else:
            return;

# Generate the merit
@app.route('/merit/generate/<course_id>', methods=['GET', 'POST'])
def generateMeritFunction(course_id,chance_memo):
    task = generateMerit(course_id,chance_memo).apply_async()
    return  redirect(url_for('taskstatus',task_id=task.id))

@app.route('/status/<task_id>')
def taskstatus(task_id):
    task = generateMeritFunction.AsyncResult(task_id)
    if task.state == 'PENDING':
        # job did not start yet
        response = {
            'state': task.state,
            'current': 0,
            'total': 1,
            'status': 'Pending...'
        }
    elif task.state != 'FAILURE':
        response = {
            'state': task.state,
            'current': task.info.get('current', 0),
            'total': task.info.get('total', 1),
            'status': task.info.get('status', '')
        }
        if 'result' in task.info:
            response['result'] = task.info['result']
    else:
        # something went wrong in the background job
        response = {
            'state': task.state,
            'current': 1,
            'total': 1,
            'status': str(task.info),  # this is the exception raised
        }
    return jsonify(response)

# Generate the merit
@app.route('/pdf/generate/', methods=['GET', 'POST'])
def generatePDFRoute():

    courses = course_information.find({'processed':True})
    if request.method=='POST':

        # Get the course ID.
        course_id = (request.form['course'])

        # Get the type of list user wants to download
        type = request.form['type']

        if type == 'select':
            # make an API call to the MongoDB server to get select list.
            course_data = merit.find({'course':course_id})

        elif type == 'chance_memo':
            # make an API call to the MongoDB server to get chance memo list.
            course_data = chance_memo_collection.find({'course': course_id})

        # extract the list of documents from cursor obj
        course_data_list = list(course_data)

        # create an empty DataFrame for storing documents
        docs = pandas.DataFrame(columns=[])

        # iterate over the list of MongoDB dict documents
        for num, doc in enumerate(course_data_list):
            # get roll_number from dict
            doc_id = doc["roll_number"]
            # create a Series obj from the MongoDB dict
            series_obj = pandas.Series(doc, name=doc_id)
            # append the MongoDB Series obj to the DataFrame obj
            docs = docs.append(series_obj)
            Path(f'results/{now.year}/{course_id}').mkdir(parents=True, exist_ok=True)
            docs.to_csv(f'results/{now.year}/{course_id}/{type}.csv', ",")

        return send_file(f'results/{now.year}/{course_id}/{type}.csv')


    return render_template('pages/pdf.html',courses=courses)


if not app.debug:
    file_handler = FileHandler('error.log')
    file_handler.setFormatter(
        Formatter('%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]')
    )
    app.logger.setLevel(logging.INFO)
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    app.logger.info('errors')


#----------------------------------------------------------------------------#
# DOWNLOAD PDF
#----------------------------------------------------------------------------#
@app.route('/file-download')
def return_file():
    return send_file(Merit.generatePDF.return_file(), attachment_filename="Result.pdf")

#----------------------------------------------------------------------------#
# ALL CELERY TASKS GO HERE...
#----------------------------------------------------------------------------#

# Create celery task here.
@celery.task(bind=True)
def generateMerit(self,course_id,chance_memo):
    merit = Merit(course_id, EB=True, chance_memo=chance_memo, sort_on='marks')
    merit.generateChanceMemo()
    course_information.update_one({'course_id': course_id},{'$set':{'processed':True}})
    return { 'status': 'Task completed!'}



#
#----------------------------------------------------------------------------#
# Launch.
#----------------------------------------------------------------------------#

# Default port:
if __name__ == '__main__':
    app.run(debug=True,port='2000')

