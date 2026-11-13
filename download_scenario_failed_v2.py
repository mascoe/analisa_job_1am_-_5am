
import dataiku
import pandas as pd
from datetime import datetime, timedelta, timezone


# ==========================================
# CONFIGURATION
# ==========================================

START_HOUR = 1
END_HOUR = 5

tz = timezone(timedelta(hours=7))

today = datetime.now(tz).replace(
    hour=0,
    minute=0,
    second=0,
    microsecond=0
)

# Last 7 days, including today
date_from = today - timedelta(days=6)
date_to = today + timedelta(days=1)

date_list = [
    (today - timedelta(days=i)).date()
    for i in reversed(range(7))
]

date_columns = [
    d.strftime('%Y-%m-%d')
    for d in date_list
]


# ==========================================
# TIMESTAMP CONVERSION
# ==========================================

def convert_timestamp(timestamp):

    if timestamp is None:
        return None

    if isinstance(timestamp, datetime):

        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(
                tzinfo=timezone.utc
            )

        return timestamp.astimezone(tz)

    timestamp = float(timestamp)

    # Convert milliseconds to seconds
    if timestamp > 1e12:
        timestamp = timestamp / 1000

    return datetime.fromtimestamp(
        timestamp,
        tz=timezone.utc
    ).astimezone(tz)


# ==========================================
# GET RUN END TIME
# ==========================================

def get_run_end_time(run):

    end_time = None

    # Try get_end_time()
    try:
        end_time = run.get_end_time()
    except Exception:
        pass

    # Fallback to run details
    if end_time is None:

        try:

            details = run.get_details()

            end_time = (
                details.get('end')
                or details.get('endTime')
                or details.get('end_time')
            )

        except Exception:
            pass

    if end_time is not None:
        return convert_timestamp(end_time)

    return None


# ==========================================
# INITIALIZATION
# ==========================================

client = dataiku.api_client()

data = []


# ==========================================
# GET ALL PROJECTS
# ==========================================

projects = client.list_projects()

for project_info in projects:

    project_key = project_info['projectKey']

    try:

        project = client.get_project(project_key)

        scenarios = project.list_scenarios(
            as_type='objects'
        )

    except Exception as e:

        print(
            'Project Error:',
            project_key,
            str(e)
        )

        continue


    # ==========================================
    # GET SCENARIOS
    # ==========================================

    for scenario in scenarios:

        try:

            settings = scenario.get_settings()

            scenario_active = settings.active

            # Only active scenarios
            if not scenario_active:
                continue

            scenario_id = scenario.id


            # ==========================================
            # INITIALIZE DAILY EVENTS
            # ==========================================

            daily_events = {
                date: []
                for date in date_columns
            }


            # ==========================================
            # GET SCENARIO RUN HISTORY
            # ==========================================

            try:

                runs = scenario.get_runs_by_date(
                    date_from,
                    date_to
                )

                for run in runs:

                    try:

                        # ==========================================
                        # RUN START TIME
                        # ==========================================

                        run_start = convert_timestamp(
                            run.get_start_time()
                        )

                        if run_start is None:
                            continue

                        run_date = run_start.strftime(
                            '%Y-%m-%d'
                        )

                        if run_date not in daily_events:
                            continue


                        # ==========================================
                        # RUN END TIME
                        # ==========================================

                        run_end = get_run_end_time(run)


                        # ==========================================
                        # SCENARIO OUTCOME
                        # ==========================================

                        run_outcome = ''

                        try:

                            run_outcome = str(
                                run.outcome
                            ).upper()

                        except Exception as e:

                            print(
                                'Scenario Outcome Not Available:',
                                project_key,
                                scenario_id,
                                str(e)
                            )


                        # ==========================================
                        # SCENARIO FAILED
                        # ==========================================

                        if run_outcome == 'FAILED':

                            failure_time = (
                                run_end
                                if run_end is not None
                                else run_start
                            )

                            failure_date = (
                                failure_time.strftime('%Y-%m-%d')
                            )

                            if failure_date in daily_events:

                                daily_events[
                                    failure_date
                                ].append({
                                    'time': failure_time,
                                    'status': 'FAILED',
                                    'end_time': None
                                })


                        # ==========================================
                        # SCENARIO SUCCESS
                        # ==========================================

                        elif run_outcome == 'SUCCESS':

                            if run_end is not None:

                                success_date = (
                                    run_end.strftime('%Y-%m-%d')
                                )

                                if success_date in daily_events:

                                    daily_events[
                                        success_date
                                    ].append({
                                        # Keep end time for event ordering
                                        'time': run_end,

                                        'status': 'SUCCESS',

                                        'end_time': run_end,

                                        # Use start time for display
                                        'start_time': run_start
                                    })

                            else:

                                print(
                                    'Run End Time Not Available:',
                                    project_key,
                                    scenario_id
                                )


                        # ==========================================
                        # CHECK STEP RUN OUTCOME
                        # ==========================================

                        try:

                            details = run.get_details()

                            step_runs = details.get(
                                'stepRuns',
                                []
                            )

                            for step_run in step_runs:

                                result = (
                                    step_run.get('result', {})
                                    or {}
                                )

                                step_outcome = str(
                                    result.get(
                                        'outcome',
                                        step_run.get('outcome', '')
                                    )
                                ).upper()

                                if step_outcome == 'FAILED':

                                    step_start = step_run.get(
                                        'start'
                                    )

                                    converted_start = (
                                        convert_timestamp(step_start)
                                    )

                                    if converted_start is not None:

                                        failure_time = converted_start

                                    else:

                                        failure_time = run_start

                                    failure_date = (
                                        failure_time.strftime('%Y-%m-%d')
                                    )

                                    if failure_date in daily_events:

                                        daily_events[
                                            failure_date
                                        ].append({
                                            'time': failure_time,
                                            'status': 'FAILED',
                                            'end_time': None
                                        })

                        except Exception as e:

                            print(
                                'Step History Error:',
                                project_key,
                                scenario_id,
                                str(e)
                            )

                    except Exception as e:

                        print(
                            'Run History Error:',
                            project_key,
                            scenario_id,
                            str(e)
                        )

            except Exception as e:

                print(
                    'Scenario History Error:',
                    project_key,
                    scenario_id,
                    str(e)
                )


            # ==========================================
            # BUILD DAILY FAILURE STATUS
            # ==========================================

            failed_dates = {}

            for date in date_columns:

                events = daily_events[date]

                # No failure on this date
                if not any(
                    event['status'] == 'FAILED'
                    for event in events
                ):
                    failed_dates[date] = ''
                    continue

                # Sort events chronologically
                events = sorted(
                    events,
                    key=lambda x: x['time']
                )

                latest_event = events[-1]

                # Failed, but eventually succeeded
                if latest_event['status'] == 'SUCCESS':

                    # Use START TIME of the successful attempt
                    start_time = latest_event['start_time']

                    failed_dates[date] = (
                        'berhasil di jam '
                        + start_time.strftime('%H:%M')
                    )

                # Failed and no later success
                else:

                    failed_dates[date] = 'tidak berhasil'


            # ==========================================
            # GET ACTIVE TRIGGERS
            # ==========================================

            triggers = settings.raw_triggers

            for trigger in triggers:

                trigger_type = trigger.get('type')

                trigger_active = trigger.get(
                    'active',
                    False
                )

                # Only active triggers
                if not trigger_active:
                    continue

                params = trigger.get(
                    'params',
                    {}
                )

                frequency = params.get(
                    'frequency',
                    ''
                )

                scheduled_hours = []

                schedule_time = ''

                schedule_description = ''


                # ==========================================
                # DAILY / WEEKLY / MONTHLY
                # ==========================================

                if frequency in [
                    'Daily',
                    'Weekly',
                    'Monthly'
                ]:

                    hour = params.get('hour')

                    minute = params.get(
                        'minute',
                        0
                    )

                    if hour is not None:

                        hour = int(hour)
                        minute = int(minute)

                        scheduled_hours = [hour]

                        schedule_time = (
                            f'{hour:02d}:{minute:02d}'
                        )

                        schedule_description = (
                            f'{frequency} {schedule_time}'
                        )

                    else:

                        schedule_description = frequency


                # ==========================================
                # HOURLY
                # ==========================================

                elif frequency == 'Hourly':

                    starting_hour = int(
                        params.get(
                            'startingHour',
                            0
                        )
                    )

                    interval = int(
                        params.get(
                            'repeatFrequency',
                            1
                        )
                    )

                    minute = int(
                        params.get(
                            'minuteOfHour',
                            0
                        )
                    )

                    schedule_description = (
                        f'Every {interval} hour(s), '
                        f'starting {starting_hour:02d}:{minute:02d}'
                    )

                    if interval > 0:

                        scheduled_hours = list(
                            range(
                                starting_hour,
                                24,
                                interval
                            )
                        )


                # ==========================================
                # MINUTELY
                # ==========================================

                elif frequency == 'Minutely':

                    repeat_frequency = int(
                        params.get(
                            'repeatFrequency',
                            1
                        )
                    )

                    schedule_description = (
                        f'Every {repeat_frequency} minute(s)'
                    )


                # ==========================================
                # OTHER TIME-BASED TRIGGERS
                # ==========================================

                elif frequency:

                    schedule_description = str(params)


                # ==========================================
                # EVENT-BASED TRIGGERS
                # ==========================================

                else:

                    schedule_description = (
                        f'Event-based: {trigger_type}'
                    )


                # ==========================================
                # FILTER SCHEDULE TIME
                # ==========================================

                matching_hours = [
                    hour
                    for hour in scheduled_hours
                    if START_HOUR <= hour < END_HOUR
                ]

                if scheduled_hours and not matching_hours:
                    continue


                # ==========================================
                # SET SCHEDULE TIME
                # ==========================================

                if frequency == 'Hourly' and matching_hours:

                    schedule_time = ', '.join(
                        f'{hour:02d}:{minute:02d}'
                        for hour in matching_hours
                    )


                # ==========================================
                # BUILD OUTPUT ROW
                # ==========================================

                row = {

                    'project_key': project_key,

                    'scenario_id': scenario_id,

                    'scenario_active': scenario_active,

                    'trigger_type': trigger_type,

                    'schedule_description': schedule_description,

                    'schedule_time': schedule_time

                }

                row.update(failed_dates)

                data.append(row)


        except Exception as e:

            print(
                'Scenario Error:',
                project_key,
                str(e)
            )


# ==========================================
# CREATE DATAFRAME
# ==========================================

fixed_columns = [
    'project_key',
    'scenario_id',
    'scenario_active',
    'trigger_type',
    'schedule_description',
    'schedule_time'
]

all_columns = fixed_columns + date_columns

df_schedule = pd.DataFrame(
    data,
    columns=all_columns
)


# ==========================================
# FILTER SCENARIOS WITH FAILED
# ==========================================

failure_values = [
    'berhasil di jam',
    'tidak berhasil'
]

df_schedule = df_schedule[
    df_schedule[date_columns]
    .apply(
        lambda col: col.astype(str).str.startswith(
            tuple(failure_values)
        )
    )
    .any(axis=1)
].copy()


# ==========================================
# SORT DATA
# ==========================================

if not df_schedule.empty:

    df_schedule = df_schedule.sort_values(
        by='schedule_time',
        na_position='last'
    ).reset_index(drop=True)


# ==========================================
# SUMMARY
# ==========================================

print('==========================================')
print('SCENARIO WITH FAILED')
print('==========================================')

print(
    'Total Scenarios with Failure:',
    len(df_schedule)
)


# ==========================================
# DISPLAY ALL ROWS AND COLUMNS
# ==========================================

pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)
pd.set_option('display.max_colwidth', None)
pd.set_option('display.width', None)


# ==========================================
# FINAL OUTPUT
# ==========================================

df_schedule
