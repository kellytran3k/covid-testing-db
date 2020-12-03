from flask import Flask, request, session, render_template, redirect, url_for

import json
import pymysql
import os
import re
import collections
import datetime
import random

app = Flask(__name__, static_url_path="")
app.secret_key = os.urandom(24)
connection = pymysql.connect(host='localhost',
                             user='root',
                             password='', # replace your db password here
                             db='covidtest_fall2020')

# Namedtuple for useful account information
Account = collections.namedtuple('Account', 'username, user_password, email, fname, lname, role')


@app.route('/', methods=['GET', 'POST'])
def login():
    msg = ''
    # Making Cursor Object For Query Execution
    if request.method == 'POST' and 'username' in request.form and 'password' in request.form:
        # Create variables for easy access
        i_username = request.form['username']
        i_password = request.form['password']

        # Check if account exists using MySQL
        cursor = connection.cursor()
        cursor.callproc('login', (i_username, i_password))

        connection.commit()
        cursor.execute('''SELECT
            username, user_password, email, fname, lname, role
            FROM login_result;''')
        user_info = cursor.fetchone()
        account = Account._make(user_info) if user_info else None
        # printf('account: {account}')

        # If account exists in accounts table in out database
        if account:
            # Create session data, we can access this data in other routes
            session['loggedin'] = True
            session['username'] = account.username
            session['role'] = account.role
            session['full_name'] = account.fname + " " + account.lname

            # Redirect to home page
            return redirect(url_for('home'))
        else:
            # Account doesnt exist or username/password incorrect
            msg = 'Incorrect username/password!'
            return render_template('index.html', msg=msg)

    return render_template('index.html', msg=msg)


@app.route('/logout', methods=['GET'])
def logout():
    session.pop('loggedin', None)
    session.pop('username', None)
    session.pop('role', None)
    return redirect(url_for('login'))


@app.route('/home')
def home():
    if session['loggedin']:
        success_msg = None
        if 'success_msg' in session:
            success_msg = session['success_msg']
            del session['success_msg']

        return render_template('home.html', role=session['role'], success_msg=success_msg)

    # User is not logged in
    return redirect(url_for('login'))


###########################################################################
#                         Michael's Screens                               #
###########################################################################


@app.route('/view_pools', methods=['GET', 'POST'])
def view_pools():
    cursor = connection.cursor()
    if request.method == 'POST':
        if 'filter' in request.form:
            # The order of these matters because they define the parameters of the db stored procedure
            filters = {
                'low_date': request.form['low_date'],
                'high_date': request.form['high_date'],
                'pool_status': request.form['pool_status'],
                'processed_by': request.form['processed_by']
            }

            for filt_name, val in filters.items():
                filters[filt_name] = val if val else None

            # Query the db for the pools
            cursor.callproc('view_pools', tuple(filters.values()))
            connection.commit()
            cursor.execute('SELECT * FROM view_pools_result;')
            pool_results = cursor.fetchall()

            # Create a list of results to display in the HTML
            pool_list = [
                {
                    'pool_id': pool_id,
                    'test_ids': test_ids,
                    'date_processed': date_processed,
                    'processed_by': processed_by,
                    'pool_status': pool_status
                }
                for pool_id, test_ids, date_processed, processed_by, pool_status
                in pool_results
            ]

            return render_template('view_pools.html', pool_list=pool_list)

    return render_template('view_pools.html')


@app.route('/process_pool/<int:pool_id>', methods=['GET', 'POST'])
def process_pool(pool_id):
    cursor = connection.cursor()

    # Query db to see which test are in this pool
    cursor.execute(f'SELECT test_id, appt_date, test_status FROM test WHERE pool_id={pool_id};')
    tests_in_pool = [
        {
            'test_id': test_id,
            'date_tested': date_tested,
            'test_status': test_status
        }
        for test_id, date_tested, test_status
        in list(cursor.fetchall())
    ]

    error = ''
    if request.method == 'POST':
        if 'process' in request.form:
            date_processed = request.form['date_processed']
            date_processed = datetime.date(*tuple(map(int, date_processed.split('-'))))
            pool_status = request.form['pool_status']
            processed_by = session['username']

            # Check for errors
            if date_processed < max([d['date_tested'] for d in tests_in_pool]):
                error = 'Date Processed must be equal to or after the latest test date in the pool'

            if error:
                return render_template('process_pool.html',
                        pool_id=pool_id,
                        tests=tests_in_pool,
                        error=error
                    )

            # Update the pool status
            cursor.callproc('process_pool', (pool_id, pool_status, date_processed, processed_by))
            connection.commit()

            # Update the test statuses in this pool
            ids_and_status = []
            for k, v in request.form.items():
                if 'test_status' in k:
                    test_id = int(k.split('_')[-1])
                    ids_and_status.append((test_id, v))

            for id_, status in ids_and_status:
                cursor.callproc('process_test', (id_, status))
                connection.commit()

            session['success_msg'] = 'Success!'
            return redirect(url_for('home'))

    return render_template('process_pool.html', pool_id=pool_id, tests=tests_in_pool)


@app.route('/view_processed_tests', methods=['GET', 'POST'])
def view_processed_tests():
    cursor = connection.cursor()

    if session['loggedin']:
        username = session['username']

        if request.method == 'POST':
            filters = {
                'username': username,
                'low_date': request.form['low_date'],
                'high_date': request.form['high_date'],
                'test_result': request.form['test_result']
            }

            for filt_name, val in filters.items():
                filters[filt_name] = val if val else None

            cursor.callproc('view_tests_for_labtech', tuple(filters.values()))
            connection.commit()

            cursor.execute('SELECT * FROM labtech_tests_result;')
            test_results = cursor.fetchall()

            # Create a list of results to display in the HTML
            test_list = [
                {
                    'test_id': test_id,
                    'pool_id': pool_id,
                    'date_tested': date_tested,
                    'date_processed': date_processed,
                    'test_status': test_status
                }
                for test_id, pool_id, date_tested, date_processed, test_status
                in test_results
            ]

            return render_template('lab_tech_tests_processed.html', test_list=test_list)

        return render_template('lab_tech_tests_processed.html')


@app.route('/create_pool', methods=['GET', 'POST'])
def create_pool():
    cursor = connection.cursor()

    # Sample a collection of potential tests for the pool
    cursor.execute('''SELECT test_id, appt_date FROM test WHERE pool_id is NULL;''')
    tests = list(cursor.fetchall())
    random.shuffle(tests)
    tests = tests[:7] # maximum number of tests in a pool
    test_for_pool = [
        {
            'test_id': test_id,
            'date_tested': date_tested,
        }
        for test_id, date_tested in tests
    ]

    # Get the current pool_id values to prevent repeats
    cursor.execute('SELECT pool_id FROM pool;')
    pool_ids = set(map(lambda x: int(x[0]), list(cursor.fetchall())))
    suggested_pool_id = max(pool_ids) + 1

    error = ''
    if request.method == 'POST':
        if 'create' in request.form:
            pool_id = request.form['pool_id']
            if pool_id in pool_ids:
                error = 'Pool Id already taken'

            checked_tests = []
            for k, v in request.form.items():
                if 'include' in k:
                    checked_tests.append(int(k.split('_')[-1]))

            if not len(checked_tests):
                error = 'Pool must have at least one test'

            if error:
                return render_template('create_pool.html', test_for_pool=test_for_pool, suggested_pool_id=suggested_pool_id, error=error)

            # Create the pool
            cursor.callproc('create_pool', (pool_id, checked_tests[0]))
            connection.commit()

            # # Insert the rest of the tests
            for test_id in checked_tests[1:]:
                cursor.callproc('assign_test_to_pool', (pool_id, test_id))
                connection.commit()

            return redirect(url_for('home'))

    return render_template('create_pool.html', test_for_pool=test_for_pool, suggested_pool_id=suggested_pool_id)


###########################################################################
#                           Yun's Screens                                 #
###########################################################################

@app.route('/explore_pool/<pool_id>', methods=['GET', 'POST'])
def explore_pool(pool_id):
    cursor = connection.cursor()

    cursor.execute('SELECT * FROM POOL where pool_id=%s;',(pool_id))
    results = cursor.fetchall()
    explore_list = [
        {
            'pool_id': pool_id,
            'pool_status': pool_status,
            'process_date': process_date,
            'processed_by': processed_by
        }
        for pool_id,pool_status,process_date, processed_by
        in results
    ]

    cursor.execute('SELECT test_id, test_status, appt_site, appt_date FROM TEST where pool_id=%s;',(pool_id))
    results2 = cursor.fetchall()
    explore2_list = [
        {
            'test_id': test_id,
            'test_status': test_status,
            'appt_site': appt_site,
            'appt_date': appt_date
        }
        for test_id,test_status,appt_site,appt_date
        in results2
    ]

    return render_template('explore_pool.html', explore_list = explore_list, explore2_list = explore2_list)


@app.route('/view_aggregate_results', methods=['GET', 'POST'])
def view_aggregate_results():

    cursor = connection.cursor()

    if session['loggedin']:
        username = session['username']

        cursor.execute('SELECT site_name FROM SITE;')
        site_list = [item[0] for item in cursor.fetchall() ]


        if request.method == 'POST':

            if 'reset' in request.form:
                return render_template('view_aggregate_results.html')

            if 'filter' in request.form:

                filters = {
                    'loc' : request.form['loc'],
                    'house': request.form['house'],
                    'site_list' : request.form['site_list'],
                    'low_date':request.form['low_date'],
                    'high_date':request.form['high_date']
                }

                for filt_name, val in filters.items():
                   filters[filt_name] = val if val else None

                # Query the db for the pools
                cursor.callproc('aggregate_results', tuple(filters.values()))
                connection.commit()
                cursor.execute('SELECT * FROM aggregate_results_result;')
                agg_result = cursor.fetchall()

                    # Create a list of results to display in the HTML
                agg_list = [
                    {
                        'test_status': test_status,
                        'num_of_test': num_of_test,
                        'percentage' : percentage
                    }
                    for test_status, num_of_test, percentage
                    in agg_result
                ]
                #{'site_name': site_name} for site_name in result]
                cursor.callproc('get_agg_total')
                connection.commit()
                cursor.execute('SELECT * FROM get_agg_total_result;')
                total_num = cursor.fetchone() [0]

                print("H")
                return render_template('view_aggregate_results.html', site_list=site_list, agg_list=agg_list,total_num=total_num)

        return render_template('view_aggregate_results.html',site_list=site_list)




@app.route('/view_my_results', methods=['GET', 'POST'])
def view_my_results():

    cursor = connection.cursor()
    if session['loggedin']:
        username = session['username']

        if request.method == 'POST':
            # The order of these matters because they define the parameters of the db stored procedure
            if 'reset' in request.form:
                print("reset")
                return render_template('view_my_results.html')

            if 'filter' in request.form:
                print("submit")
                filters = {
                    'username' : username,
                    'pool_status': request.form['pool_status'],
                    'low_date':request.form['low_date'],
                    'high_date':request.form['high_date']
                }

                for filt_name, val in filters.items():
                   filters[filt_name] = val if val else None

                # Query the db for the pools
                cursor.callproc('student_view_results', tuple(filters.values()))
                connection.commit()
                cursor.execute('SELECT * FROM student_view_results_result;')
                student_results = cursor.fetchall()

                # Create a list of results to display in the HTML
                student_list = [
                    {
                        'test_id': test_id,
                        'timeslot_date': timeslot_date,
                        'date_processed': date_processed,
                        'pool_status': pool_status,
                        'test_status': test_status
                    }
                    for test_id, timeslot_date, date_processed, pool_status, test_status
                    in student_results
                ]

                return render_template('view_my_results.html', student_list=student_list)
        return render_template('view_my_results.html')

@app.route('/explore_result/<test_id>', methods=['GET', 'POST'])
def explore_result(test_id):
    cursor = connection.cursor()

    cursor.callproc('explore_results', [test_id])
    connection.commit()
    cursor.execute('SELECT * FROM explore_results_result;')
    results = cursor.fetchone()


    if results == None:
        msg = "You cannot explore a pending test."
        return render_template('explore_result.html', msg = msg)

    else:
        cursor.execute('SELECT * FROM explore_results_result;')
        results = results = cursor.fetchall()
        explore_list = [
            {
                'test_id': test_id,
                'test_date': test_date,
                'timeslot': timeslot,
                'testing_location': testing_location,
                'date_processed': date_processed,
                'pooled_result': pooled_result,
                'individual_result':individual_result,
                'processed_by':processed_by
            }
            for test_id,test_date,timeslot,testing_location,date_processed,pooled_result,individual_result, processed_by
            in results
        ]

        return render_template('explore_result.html', explore_list = explore_list)

@app.route('/signup_test', methods=['GET', 'POST'])
def signup_test():
    msg =''
    cursor = connection.cursor()
    if session['loggedin']:
        username = session['username']

        cursor.execute('SELECT site_name FROM SITE;')
        #result = cursor.fetchall()
        site_list = [ item[0] for item in cursor.fetchall() ]
        #{'site_name': site_name} for site_name in result]
        cursor.callproc('student_view_results', (username,None,None,None))
        connection.commit()
        cursor.execute('SELECT test_status FROM student_view_results_result;')
        sta = cursor.fetchall()
        #sta = [{'test_status' : test_status}for test_status in sta]
        can_sign_in = True
        for test in sta:
            for t in test:
                if t =='pending':
                    print("yes")
                    can_sign_in = False

        if can_sign_in:
            if request.method == 'POST':
                filters = {
                    'username' : username,
                    'site_list' : request.form['site_list'],
                    'low_date':request.form['low_date'],
                    'high_date':request.form['high_date'],
                    'low_time':request.form['low_time'],
                    'high_time':request.form['high_time']
                }

                for filt_name, val in filters.items():
                   filters[filt_name] = val if val else None

                # Query the db for the pools
                cursor.callproc('test_sign_up_filter', tuple(filters.values()))
                connection.commit()
                cursor.execute('SELECT appt_date,appt_time,street,site_name FROM test_sign_up_filter_result;')
                _result = cursor.fetchall()

                    # Create a list of results to display in the HTML
                signup_list = [
                    {
                        'appt_date': appt_date,
                        'appt_time': appt_time,
                        'street' : street,
                        'site_name' : site_name
                    }
                    for appt_date, appt_time, street, site_name
                    in _result
                ]
                if 'reset' in request.form:
                    return render_template('signup_test.html')

                if 'process' in request.form:
                    print("hi")
                    cursor.callproc('get_testid')
                    connection.commit()
                    cursor.execute('SELECT test_id FROM get_testid_result;')
                    tid = str(cursor.fetchone()[0])

                    print(tid)
                    print(request.form['asite'])
                    print(request.form['adate'])
                    print(request.form['atime'])

                    appt = {
                        'username' : username,
                        'asite' : request.form['asite'],
                        'adate':request.form['adate'],
                        'atime':request.form['atime'],
                        'tid' : tid

                    }
                    cursor.callproc('test_sign_up', tuple(appt.values()))
                    connection.commit()

                    #return redirect(url_for('signup_test'))
                    msg= "You've successfully signed up for a test. You can't sign up again with a pending test."
                    return render_template('signup_test.html',site_list=site_list, msg = msg)

                return render_template('signup_test.html', site_list=site_list, signup_list=signup_list)

        if not can_sign_in:
            msg = "You currently have a pending test. You can't sign up for a test"

        return render_template('signup_test.html',site_list=site_list, msg = msg)


# -----------  K E L L Y ' S  ------- S C R E E N S -----------------

@app.route('/view_daily_results', methods=['GET', 'POST'])
def view_daily_results():
    msg = ''
    # connects w database
    cursor = connection.cursor()
    # calls daily_results on database
    cursor.callproc('daily_results')
    connection.commit()

    # fetches the daily results
    cursor.execute('SELECT * FROM daily_results_result')
    resultDetails = cursor.fetchall()

    # returns daily results
    return render_template('view_daily_results.html', resultDetails=resultDetails)


@app.route('/view_appointments', methods=['GET', 'POST'])
def view_appointments():
    # connects w database
    cursor = connection.cursor()
    msg = ''

    cursor.execute('SELECT site_name FROM site')
    all_sites = [row[0] for row in cursor.fetchall()]

    print("all_sites: " + str(all_sites))

    if request.method == 'POST':
        if 'filter' in request.form:
            # The order of these matters because they define the parameters of the view_appt procedure
            filters = {
                'site_name': request.form['site_name'],
                'begin_appt_date': request.form['begin_appt_date'],
                'end_appt_date': request.form['end_appt_date'],
                'begin_appt_time': request.form['begin_appt_time'],
                'end_appt_time': request.form['end_appt_time'],
                'is_available': request.form['is_available']
            }

            for filt_name, val in filters.items():
                    if filt_name == 'is_available':
                        filters[filt_name] = int(val) if val else None
                    else:
                        filters[filt_name] = val if val else None

            print(filters)

            # calls daily_results on database
            cursor.callproc('view_appointments', tuple(filters.values()))
            connection.commit()
            cursor.execute('SELECT * FROM view_appointments_result;')
            appointmentResults = cursor.fetchall()

            print(appointmentResults)

            # Create a list of results to display in the HTML
            appointment_list = [
                {
                    'appt_date': appt_date,
                    'appt_time': appt_time,
                    'site_name': site_name,
                    'location': location,
                    'username': username
                }
                for appt_date, appt_time, site_name, location, username
                in appointmentResults
            ]
            return render_template('view_appointments.html', appointment_list=appointment_list, all_sites=all_sites)
    return render_template('view_appointments.html', all_sites=all_sites)

@app.route('/register', methods=['GET', 'POST'])
def register():
    # Output message if something goes wrong...
    msg = ''
    # Check if POST requests exist (user submitted form)
    if request.method == 'POST':
        # Create variables for easy access
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        firstname = request.form['firstname']
        lastname = request.form['lastname']
        email = request.form['email']
        if email:
            if (not re.match(r'[^@]+@[^@]+\.[^@]+', email)) or len(email) < 5 or len(email) > 25:
                msg = 'Invalid email address!'
                return render_template('register.html', msg=msg)
        else:
            msg = 'Please enter valid email'
            return render_template('register.html', msg=msg)

	# Check if account exists using MySQL
        cursor = connection.cursor()
        cursor.execute('SELECT * FROM user WHERE username = %s', (username))
        account = cursor.fetchone()
        cursor.execute('SELECT * FROM user WHERE fname = %s AND lname = %s', (firstname, lastname))
        name = cursor.fetchone()
		# If account exists show error and validation checks
        if account:
            msg = 'Account already exists!'
            return render_template('register.html', msg=msg)
        elif not re.match(r'[A-Za-z0-9]+', username):
            msg = 'Username must contain only characters and numbers!'
            return render_template('register.html', msg=msg)
        elif len(password) < 8:
            msg = 'Please choose a password length of at least 8!'
            return render_template('register.html', msg=msg)
        elif password != confirm_password:
            msg = 'Passwords do not match!'
            return render_template('register.html', msg=msg)
        elif name:
            msg = 'This person already has an account'
            return render_template('register.html', msg=msg)
        role = request.form['role']
        if role == 'Student':
            housing = request.form['housing']
            location = request.form['location']
            cursor.callproc('register_student', (username, email, firstname, lastname, location, housing, password))
            connection.commit()
            cursor.close()
            msg = 'You have successfully registered!'
        elif role == 'Employee':
            phonenumber = request.form['phonenumber']
            if request.form.get('sitetester'):
                istester = True
            else:
                istester = False
            if request.form.get('labtech'):
                islabtech = True
            else:
                islabtech = False
            if istester == False and islabtech == False:
                msg = 'Employee must be a site tester or a lab technician!'
                return render_template('register.html', msg=msg)
            cursor.callproc('register_employee', (username, email, firstname, lastname, phonenumber, islabtech, istester, password))
            connection.commit()
            cursor.close()
            msg = 'You have successfully registered!'
    return render_template('register.html', msg=msg)


@app.route('/createtestingsite', methods=['GET', 'POST'])
def create_testing_site():
    msg = ''
    cursor = connection.cursor()
    cursor.execute('SELECT username, fname, lname FROM user, sitetester WHERE user.username = sitetester.sitetester_username')
    testList = cursor.fetchall()
    if request.method == 'POST':
        sitename = request.form['sitename']
        cursor.execute('SELECT site_name FROM site where site_name = %s', (sitename,))
        if cursor.fetchone():
            msg = 'Site already exists'
            return render_template("createtestingsite.html", testerList = testList, msg = msg)
        streetaddress = request.form['address']
        city = request.form['city']
        state = request.form['state']
        zip = request.form['zip']
        if not re.match('^[0-9]{5}$', zip):
            msg = 'Invalid zip code'
            return render_template("createtestingsite.html", testerList = testList, msg = msg)
        location = request.form['location']
        sitetester = request.form['sitetester']
        cursor.callproc('create_testing_site', (sitename, streetaddress, city, state, zip, location, sitetester))
        connection.commit()
        cursor.close()
        msg = 'Site creation successful!'
    return render_template("createtestingsite.html", testerList = testList, msg = msg)


@app.route('/reassigntester', methods=['GET', 'POST'])
def reassigntester():
    msg = ""
    cursor = connection.cursor()
    cursor.execute('SELECT username, fname, lname, phone_num from user,employee,sitetester where user.username = sitetester.sitetester_username and user.username = emp_username')
    testerList = cursor.fetchall()
    usernameList = []
    sitelist = []
    sitelist2 = []
    nonsitelist = []
    nonsitelist2 = []
    k = 0
    cursor.execute('SELECT DISTINCT site_name FROM SITE')
    fullsitelist = cursor.fetchall()
    fullsitelist2 = []
    for site in fullsitelist:
        fullsitelist2.append(site[0].replace(" ", ""))
    for tester in testerList:
        s = tester[0]
        #s = html.escape(s)
        usernameList.append(s)
        nonsitelist.append([])
        nonsitelist2.append([])
        cursor.execute('SELECT site FROM working_at WHERE username = %s', (tester[0],))
        sitelist.append(cursor.fetchall())
        for site in fullsitelist:
            if site not in sitelist[k]:
                nonsitelist[k].append(site[0])
                nonsitelist2[k].append(site[0].replace(" ", ""))
        k = k+1
    k = 0
    for site in sitelist:
        sitelist2.append([])
        for s in site:
            sitelist2[k].append(s[0].replace(" ", ""))
        k = k + 1
    if request.method == 'POST':
        k = 0
        for name in usernameList:
            str = 'sitetester' + name
            if str in request.form:
                concat_list = request.form.getlist(str)
                index = 0
                for site in fullsitelist2:
                    sname = fullsitelist[index][0]
                    cursor.execute('SELECT * FROM working_at where username = %s and site = %s', (name, sname))
                    status = cursor.fetchone()
                    if site not in concat_list:
                        if not status:
                            cursor.callproc('assign_tester', (name, sname))
                            connection.commit()
                    elif status:
                        cursor.callproc('unassign_tester', (name, sname))
                        connection.commit()
                    index = index + 1

        return redirect(url_for('reassigntester'))
    cursor.close()
    return render_template("reassigntester.html", testerList = testerList, usernameList = usernameList, sitelist = sitelist, sitelist2 = sitelist2, nonsitelist = nonsitelist, nonsitelist2 = nonsitelist2, msg = msg)

@app.route('/create_appointment', methods=['GET', 'POST'])
def create_appointment():
    msg = ''
    allowed = ['']
    # connects w database
    cursor = connection.cursor()

    cursor.execute('SELECT site_name FROM site')
    all_sites = [row[0] for row in cursor.fetchall()]

    if request.method == 'POST':
        if 'submit' in request.form:

            cursor.execute('SELECT site_name FROM site')
            all_sites = [row[0] for row in cursor.fetchall()]

            # gets data of current user
            user = session['username']
            role = session['role']

            if role == 'Sitetester':
                cursor.execute("SELECT distinct(site) FROM working_at, sitetester WHERE username = (%s)", (user))
                allowed = [row[0] for row in cursor.fetchall()]

            if role == 'Admin':
                allowed = cursor.execute("SELECT distinct(site_name) FROM site")
                allowed = [row[0] for row in cursor.fetchall()]

            print(allowed)

            # gets the inputs
            filters = {
                'site_name': request.form['site_name'],
                'appt_date': request.form['appt_date'],
                'appt_time': request.form['appt_time'],
            }

            # processes the inputs
            for filt_name, val in filters.items():
                if val:
                    if filt_name == 'site_name':
                        if val in allowed:
                            filters[filt_name] = val
                        else:
                            msg = 'Please only create appointments in your assigned sites at ' + str(allowed)
                            return render_template('create_appointment.html', msg=msg, all_sites=all_sites)
                    else:
                        filters[filt_name] = val
                else:
                    msg = 'Please input all values in correct formats'
                    return render_template('create_appointment.html', msg=msg, all_sites=all_sites)

            print(filters)

            # calls create_appointment on database
            try:
                cursor.callproc('create_appointment', tuple(filters.values()))
                connection.commit()
                msg = 'Sucessfully created appointment!'
                return render_template('create_appointment.html', msg=msg, all_sites=all_sites)
            except:
                msg = 'Appointment creation failed. Try again with different values.'
                return render_template('create_appointment.html', msg=msg, all_sites=all_sites)

    return render_template('create_appointment.html', msg=msg, all_sites=all_sites)




@app.route('/change_testing_site', methods=['GET', 'POST'])
def change_testing_site():
    msg = []

    # connects w database
    cursor = connection.cursor()
    assigned_sites = ''

    #sets user for whoever is logged in.
    tester_user = session['username']

    #sets full name for whoever is logged in.
    full_name = session['full_name']

    # selects all possible sites from database
    cursor.execute('SELECT site_name FROM site')
    all_sites = [row[0] for row in cursor.fetchall()]

    # selects the sites that user works at
    cursor.execute("SELECT distinct(site) FROM working_at, sitetester WHERE username = (%s)", (tester_user))
    assigned_sites = [row[0] for row in cursor.fetchall()]

    print(assigned_sites)
    print("done")

    if request.method == 'POST':
        if 'submit' in request.form:

            print("submitting")
            print(request.form)

            # iterates and adds all checked sites into checked_sites
            checked_sites = set()
            for k, v in request.form.items():
                if k in all_sites:
                    checked_sites.add(k)

            for site in assigned_sites:
                if site not in checked_sites:
                    cursor.callproc('unassign_tester', args=(tester_user, site))
                    rowcount = cursor.rowcount
                    connection.commit()

                    if rowcount > 0:
                        msg.append('Successfully unassigned ' + str(site) + '\n')
                    else:
                        msg.append('Failed unassinged ' + str(site) + '\n')


            for site in checked_sites:
                if site not in assigned_sites:
                    cursor.callproc('assign_tester', args=(tester_user, site))
                    rowcount = cursor.rowcount
                    connection.commit()

                    if rowcount > 0:
                        msg.append('Successfully added ' + str(site) + '\n')
                    else:
                        msg.append('Failed added ' + str(site) + '\n')


            all_sites.clear()
            assigned_sites.clear()

            # selects updated all possible sites from database
            cursor.execute('SELECT distinct(site_name) FROM site')
            all_sites = [row[0] for row in cursor.fetchall()]
            print("all_sites: " + str(all_sites))

            # selects updated sites that user works at
            cursor.execute("SELECT distinct(site) FROM working_at, sitetester WHERE username = (%s)", (tester_user))
            assigned_sites = [row[0] for row in cursor.fetchall()]

            return render_template('change_testing_site.html', tester_user=tester_user, full_name=full_name, assigned_sites=assigned_sites, all_sites=all_sites, msg=msg)

    return render_template('change_testing_site.html', tester_user=tester_user, full_name=full_name, assigned_sites=assigned_sites, all_sites=all_sites, msg=msg)
