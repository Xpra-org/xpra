#!/usr/bin/env python

import csv
import collections, math

#----------------------------------------------------------------
# The files this generator acts upon are the CSV files output
# from one or more runs of test_measure_perf.py.
#
# Data file naming convention: prefix_id_rep.csv
#
# This script takes no arguments. When it's run, it will
# produce an HTML file called "test_perf_charts.html".
#
# Open that file in your browser to see the charts.
#----------------------------------------------------------------

#----------------------------------------------------------------
# The following variables will all need to be edited to match
# the tests that you are charting
#----------------------------------------------------------------
#
# vpx is now vp8
# x264 is now h264
#
# TODO
# -- Move the legend into the chart title area
# -- Abbreviate the app names so they fit on the chart
# -- Update the documentation to describe how to use multiple unique
#    directories containing files with same key, instead of one directory
#    and files with unique keys.
#

# Location of the data files
#base_dir = "/home/nickc/xtests/logs/0.15.0"
base_dir = "/home/nickc/xtests/logs/smo"

# Data file prefix
prefix = "smo_test"
#prefix = "h264_glx"
#prefix = "all_tests_40"

# Result subdirectories
#subs = ["0.15.0", "8585_1", "8585_2", "8585_3"]
#subs = ["hv", "h1", "h2", "h3"]
#subs = ["8585_2", "9612_2"]
#subs = []

# id is the actual id string used in the data file name
# dir is an optional subdirectory within the base_dir where the data is stored
# display is how that parameter should be displayed in the charts
#params = [
#    {"id": "9612", "dir": subs[0], "display": "0"},
#    {"id": "9612", "dir": subs[1], "display": "1"},
#    {"id": "9612", "dir": subs[2], "display": "2"},
#    {"id": "9612", "dir": subs[3], "display": "3"}
#]

#params = [
#    {"id": "8585", "display": "8585"},
#    {"id": "9612", "display": "9612"}
#]

params = [
    {"id": "15r10784", "display": "15.6"},
    {"id": "16r10655", "display": "16"}
]

# The description will be shown on the output page
description = 'Comparison of v15 and v16.'

# Each file name's 'rep' value is the sequence number of that
# data file, when results of multiple files should be averaged
reps = 5     # Number of data files in each set

#----------------------------------------------------------------
# Set any of the values in the following lists to 1 in order to
# include that test app, or metric column in the chart page.
#
apps = {"glxgears": 0,
        "glxspheres": 0,
        "glxspheres64": 0,
        "moebiusgears": 0,
        "polytopes": 0,

        "x11perf": 0, # Not reliable
        "xterm": 0,
        "gtkperf": 0,
        "memscroller": 0,
        "deluxe": 0,

        "eruption": 1,
        "vlc sound visual": 1,
        "vlc video": 1,
        "xonotic-glx": 1}

metrics = {"Regions/s": 1,
           "Pixels/s Sent": 1,
           "Encoding Pixels/s": 1,
           "Decoding Pixels/s": 1,
           "Application packets in/s": 1,
           "Application bytes in/s": 1,
           "Application packets out/s": 1,
           "Application bytes out/s": 1,
           "Frame Total Latency": 1,
           "Client Frame Latency": 1,
           "client user cpu_pct": 1,
           "client system cpu pct": 1,
           "client number of threads": 1,
           "client vsize (MB)": 1,
           "client rss (MB)": 1,
           "server user cpu_pct": 1,
           "server system cpu pct": 1,
           "server number of threads": 1,
           "server vsize (MB)": 1,
           "server rss (MB)": 1,
           "Min Batch Delay (ms)": 1,
           "Avg Batch Delay (ms)": 1,
           "Max Batch Delay (ms)": 1,
           "Min Damage Latency (ms)": 1,
           "Avg Damage Latency (ms)": 1,
           "Max Damage Latency (ms)": 1,
           "Min Quality": 1,
           "Avg Quality": 1,
           "Max Quality": 1,
           "Min Speed": 0,
           "Avg Speed": 0,
           "Max Speed": 0}

encodings = {"png": 1,
             "rgb": 1,
             "rgb24": 0,
             "h264": 1,
             "jpeg": 1,
             "vp8": 1,
             "vp9": 1,
             "mmap": 1}

header_dupes = []
headers = {}
titles = []
param_ids = []
param_names = []
displayed_encodings = {}

ENCODING_RGB24 = "rgb24"

def tree():
    return collections.defaultdict(tree)
tests = tree()

def ftree():
    return collections.defaultdict(float)

# Create test map -- schema:
# {metric: {encoding: {id: {app: {rep: avg_value}}}}}
def accumulate_values(file_name, rep, param, uniqueId):
    rownum = 0
    rgb_count = 0
    rgb_values = None
    #print "uniqueid ", uniqueId

    ifile = open(file_name, "rb")
    for row in csv.reader(ifile, skipinitialspace=True):
        if (rownum == 0):
            if (len(headers) == 0):
                get_headers(row)
        else:
            app = get_value(row, "Test Command")
            if (not app in apps):
                print("Application: " + app + " not defined.")
                exit()

            if (apps[app] == 1):
                encoding = get_value(row, "Encoding")
                # x264 is now h264
                if (encoding == 'x264'):
                    encoding = 'h264'
                # vpx is now vp8
                if (encoding == 'vpx'):
                    encoding = 'vp8'

                if (not encoding in encodings):
                    print("Encoding: " + encoding + " not defined.")
                    exit()

                if (encodings[encoding] == 1):
                    displayed_encodings[encoding] = encoding;
                    if (encoding == ENCODING_RGB24):
                        if (rgb_values is None):
                            rgb_values = ftree()
                            rgb_count = 0

                    for metric in metrics:
                        if (metrics[metric] == 1):
                            row_value = float(get_metric(row, metric))
                            if (encoding == ENCODING_RGB24):
                                if (metric in rgb_values.keys()):
                                    rgb_values[metric] += row_value
                                else:
                                    rgb_values[metric] = row_value
                            else:
                                tests[metric][encoding][uniqueId][app][rep] = row_value

                    if (encoding == ENCODING_RGB24):
                        rgb_count += 1
                        if (rgb_count == 3):
                            for metric in metrics:
                                if (metrics[metric] == 1):
                                    tests[metric][encoding][uniqueId][app][rep] = rgb_values[metric] / 3
                            rgb_count = 0
                            rgb_values = None
        rownum += 1
    ifile.close()

def write_html():
    app_count = 0
    for app in apps.keys():
        if (apps[app] == 1):
            app_count += 1

    chart_count = 0
    for encoding in displayed_encodings.keys():
        if (encodings[encoding] == 1):
            chart_count += 1
    row_count = math.ceil(chart_count / 2.0)
    box_height = row_count * 400

    ofile = open("charts.html", "w")
    ofile.write('<!DOCTYPE html>\n')
    ofile.write('<html>\n')
    ofile.write('<head>\n')
    ofile.write('  <meta http-equiv="Content-Type" content="text/html; charset=utf-8">\n')
    ofile.write('  <title>Xpra Performance Results</title>\n')
    ofile.write('  <link href="css/xpra.css" rel="stylesheet" type="text/css">\n')
    ofile.write('  <script language="javascript" type="text/javascript" src="js/jquery.js"></script>\n')
    ofile.write('  <script language="javascript" type="text/javascript" src="js/jquery.flot.js"></script>\n')
    ofile.write('  <script language="javascript" type="text/javascript" src="js/jquery.flot.categories.js"></script>\n')
    ofile.write('  <script language="javascript" type="text/javascript" src="js/jquery.flot.orderbars_mod.js"></script>\n')
    ofile.write('  <script language="javascript" type="text/javascript" src="js/xpra.js"></script>\n')
    ofile.write('  <script language="javascript" type="text/javascript">\n')
    ofile.write('    var options = {canvas:true, grid: {margin: {top:50}, hoverable: true}, series: {bars: {show: true, barWidth: 0.08}}, '
                #' xaxis: {mode: "categories", tickLength: 0, min: -0.3, max: ' + str(app_count) +'}, colors: ["#cc0000", "#787A40", "#9FBF8C", "#C8AB65", "#D4CBC3"]};\n')
                ' xaxis: {mode: "categories", tickLength: 0, min: -0.3, max: ' + str(app_count) +'}, colors: ["#688b8a", "#a57c65"]};\n')

    m_index = 0
    m_names = []
    for metric in sorted(tests.keys()):
        m_names.append(metric)
        e_names = []
        for encoding in sorted(tests[metric].keys()):
            e_names.append(encoding)
            titles.append(metric + ' ( ' + encoding + ' )')
            for param in sorted(tests[metric][encoding].keys()):
                ofile.write('    var e' + str(m_index) + '_' + encoding + '_' + param + ' = [')
                for app in sorted(tests[metric][encoding][param].keys()):
                    value = 0
                    actual_reps = 0
                    for rep in sorted(tests[metric][encoding][param][app].keys()):
                        value += float(tests[metric][encoding][param][app][rep])
                        actual_reps += 1
                    value = value / actual_reps
                    ofile.write('["' + app + '", ' + str(value) + '], ')
                ofile.write('];' + '\n')
            varStr = '    var d' + str(m_index) + '_' + encoding + ' = ['
            for i in range(0, len(param_ids)):
                if (i > 0):
                    varStr += ','
                varStr += '{label: "' + param_names[i] + '", data: e' + str(m_index) + '_' + encoding + '_' + param_ids[i] + ', bars:{order:' + str(i) + '}}'
            varStr += '];\n'
            ofile.write(varStr)
        m_index += 1

    chart_index = 0
    m_index = 0
    ofile.write('    $(function() {\n')
    for metric in sorted(tests.keys()):
        e_index = 0
        for encoding in sorted(tests[metric].keys()):
            ofile.write('        var plot' +str(chart_index)+ ' = $.plot($("#placeholder_' + str(m_index) + '_' + str(e_index) + '"), d' + str(m_index) + '_' + e_names[e_index] + ', options);\n')
            e_index += 1
            chart_index += 1
        m_index += 1
    title_index = 0

    for metric in sorted(tests.keys()):
        for encoding in sorted(tests[metric].keys()):
            ofile.write('        set_title(' + str(title_index) + ', "' + titles[title_index] + '");\n')
            title_index += 1

    for mx in range(0, m_index):
        ofile.write('$("#metric_link_'+str(mx)+'").click(function() {$("#metric_list").scrollTop(' + str(box_height) + '*'+str(mx)+');});')
    ofile.write('    });\n')
    ofile.write('  </script>\n')
    ofile.write('  <style>.metric_box {height: ' + str(box_height) + 'px}</style>\n')
    ofile.write('</head>\n')
    ofile.write('<body>\n')
    ofile.write('  <div id="page">\n')
    ofile.write('    <div id="header_box">\n')
    ofile.write('      <div id="header">\n')
    ofile.write('        <h2>Xpra Performance Results</h2>\n')
    ofile.write('        <h3>' + description + '</h3>\n')
    ofile.write('        <div id="help_text">Click a metric to locate it in the results.</div>\n')
    ofile.write('      </div>\n')

    ofile.write('      <div id="select_box">\n')
    m_index = 0
    for metric in sorted(tests.keys()):
        ofile.write('        <div id="metric_link_' + str(m_index) + '" style="float:left;height:20px;width:200px"><a href="#">' + metric + '</a></div>\n')
        m_index += 1
    ofile.write('      </div>\n')
    ofile.write('    </div>\n')

    ofile.write('    <div style="clear:both"></div>\n')
    ofile.write('    <div id="metric_list">\n')
    m_index = 0
    for metric in sorted(tests.keys()):
        ofile.write('      <div class="metric_box" id="metric_box_' + str(m_index) + '">\n')
        ofile.write('        <div class="metric_label">' + metric + '</div>\n')
        e_index = 0
        for encoding in sorted(tests[metric].keys()):
            ofile.write('        <div class="container">\n')
            ofile.write('          <div id="placeholder_' + str(m_index) + '_' + str(e_index) + '" class="placeholder"></div>\n')
            ofile.write('        </div>\n')
            e_index += 1

        ofile.write('      </div>\n')
        m_index += 1
    ofile.write('      <div class="metric_box"></div>\n')
    ofile.write('    </div>\n')
    ofile.write('  </div>\n')
    ofile.write('</body>\n')
    ofile.write('</html>\n')
    ofile.close()

def col_index(label):
    return headers[label]

def get_value(row, label):
    return row[col_index(label)].strip()

def get_metric(row, label):
    cell = row[col_index(label)]
    if cell is None or cell is '':
        cell = '0'
    return cell.strip()

def sanitize(dirName):
    # Make the directory name valid as a javascript variable
    newName = dirName.replace('.', '_')
    return newName

def get_headers(row):
    index = 0
    for column in row:
        col = column.strip()
        if col in headers:
            header_dupes.append(col)
        headers[col] = index
        index += 1

def print_headers():
    for entry in headers:
        print(entry + " " + str(headers[entry]))
    for entry in header_dupes:
        print("Found dupe: %s" % entry)

def main():
    for param in params:
        param_id = param_name = param['id']
        if ('dir' in param.keys()):
            param_id = sanitize(param['dir'])
        if ('display' in param.keys()):
            param_name = param['display']
        param_ids.append(param_id)
        param_names.append(param_name)

    for param in params:
        uniqueId = param['id']
        if ('dir' in param.keys()):
            uniqueId = sanitize(param['dir'])

        for rep in range(0, reps):
            if ('dir' in param.keys()):
                file_name = base_dir + '/' + param['dir'] + '/' + prefix + '_' + param['id'] + '_' + str(rep+1) + '.csv'
            else:
                file_name = base_dir + '/' + prefix + '_' + param['id'] + '_' + str(rep+1) + '.csv'
            print "Processing: ", file_name
            accumulate_values(file_name, rep, param, uniqueId)
    write_html()
    print('\nCreated: charts.html\n')

if __name__ == "__main__":
    main()

