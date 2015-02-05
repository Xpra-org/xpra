#!/usr/bin/env python

import re
import sys
import os.path
import time
import csv
import codecs
import collections
from collections import defaultdict

#----------------------------------------------------------------
# The files this generator acts upon are the CSV files output
# from one or more runs of test_measure_perf.py.
#
# Data file naming convention: prefix_id_rep.csv
#
# This script takes no arguments. When it's run, it will
# produce and HTML file called "test_perf_charts.html".
#
# Open that file in your browser to see the charts.
#----------------------------------------------------------------
#
data_dir = "./data"

# Data file prefix
prefix = "all_tests_40"

# id is the actual id string used in the data file name
# display is how that parameter should be shown in the charts
params = [{"id": "14", "display": "v14"},
          {"id": "15", "display": "v15"}]

# The file name 'rep' value is the sequence number of that 
# data file, when results of multiple files should be averaged
reps = 9     # Number of data files in this set

#----------------------------------------------------------------
# Set any of the values in the following lists to 1 to include 
# when generating the charts
# 
apps = {"glxgears": 1, 
        "glxspheres": 1, 
        "moebiusgears": 1, 
        "polytopes": 1, 
        "x11perf": 0, 
        "xterm": 1,
        "gtkperf": 0}

metrics = {"Regions/s": 0, 
           "Pixels/s Sent": 0,
           "Encoding Pixels/s": 1, 
           "Decoding Pixels/s": 0, 
           "Application packets in/s": 0,
           "Application bytes in/s": 0,
           "Application packets out/s": 1,
           "Application bytes out/s": 0,
           "client user cpu_pct": 0,
           "client system cpu pct": 0,
           "client number of threads": 0,
           "client vsize (MB)": 0,
           "client rss (MB)": 0,
           "server user cpu_pct": 1,
           "server system cpu pct": 0,
           "server number of threads": 0,
           "server vsize (MB)": 0,
           "server rss (MB)": 0,
           "Min Batch Delay (ms)": 0,
           "Avg Batch Delay (ms)": 0,
           "Max Batch Delay (ms)": 0,
           "Min Damage Latency (ms)": 0,
           "Avg Damage Latency (ms)": 0,
           "Max Damage Latency (ms)": 0,
           "Min Quality": 0,
           "Avg Quality": 0,
           "Max Quality": 0,
           "Min Speed": 0,
           "Avg Speed": 0,
           "Max Speed": 0}

encodings = {"jpeg": 1,
             "mmap": 1,
             "png": 1,
             "rgb24": 1,
             "vpx": 1,
             "x264": 1}

header_dupes = []
headers = {}
titles = []
param_ids = []
param_names = []

ENCODING_RGB24 = "rgb24"

def tree():
    return collections.defaultdict(tree)
tests = tree()

def ftree():
    return collections.defaultdict(float)

# Create test map -- schema:
# {metric: {encoding: {param: {app: {rep: avg_value}}}}}
def accumulate_values(file_name, rep, param):
    rownum = 0
    rgb_count = 0
    rgb_values = None

    ifile = open(file_name, "rb")
    for row in csv.reader(ifile, skipinitialspace=True):
        if (rownum == 0):
            if (len(headers) == 0):
                get_headers(row)
        else:
            app = get_value(row, "Test Command")
            if (apps[app] == 1):
                encoding = get_value(row, "Encoding")
                if (encodings[encoding] == 1):
                    if (encoding == ENCODING_RGB24):
                        if (rgb_values is None):
                            rgb_values = ftree()
                            rgb_count = 0
                    for metric in metrics:
                        if (metrics[metric] == 1):
                            row_value = float(get_value(row, metric))
                            if (encoding == ENCODING_RGB24):
                                if (metric in rgb_values.keys()):
                                    rgb_values[metric] += row_value
                                else:
                                    rgb_values[metric] = row_value
                            else:
                                tests[metric][encoding][param['id']][app][rep] = row_value
                    if (encoding == ENCODING_RGB24):
                        rgb_count += 1
                        if (rgb_count == 3):
                            for metric in metrics:
                                if (metrics[metric] == 1):
                                    tests[metric][encoding][param['id']][app][rep] = rgb_values[metric] / 3
                            rgb_count = 0
                            rgb_values = None
        rownum += 1
    ifile.close()

def write_html():
    app_count = 0
    for app in apps.keys():
        if (apps[app] == 1):
            app_count += 1

    ofile = open("test_perf_charts.html", "w")
    ofile.write('<!DOCTYPE html>\n')
    ofile.write('<html>\n')
    ofile.write('<head>\n')
    ofile.write('  <meta http-equiv="Content-Type" content="text/html; charset=utf-8">\n')
    ofile.write('  <title>Xpra Performance Results</title>\n')
    ofile.write('  <link href="css/xpra.css" rel="stylesheet" type="text/css">\n')
    ofile.write('  <!--[if lte IE 8]><script language="javascript" type="text/javascript" src="../../excanvas.min.js"></script><![endif]-->\n')
    ofile.write('  <script language="javascript" type="text/javascript" src="js/jquery.js"></script>\n')
    ofile.write('  <script language="javascript" type="text/javascript" src="js/jquery.flot.js"></script>\n')
    ofile.write('  <script language="javascript" type="text/javascript" src="js/jquery.flot.categories.js"></script>\n')
    ofile.write('  <script language="javascript" type="text/javascript" src="js/jquery.flot.orderbars_mod.js"></script>\n')
    ofile.write('  <script language="javascript" type="text/javascript" src="js/xpra.js"></script>\n')
    ofile.write('  <script language="javascript" type="text/javascript">\n')
    ofile.write('    var options = {canvas:true, grid: {margin: {top:50}, hoverable: true}, series: {bars: {show: true, barWidth: 0.15}}, '
                ' xaxis: {mode: "categories", tickLength: 0, min: -0.3, max: ' + str(app_count-1) + '.3}, colors: ["#89A54E", "#4572A7"]};\n')

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
            ofile.write('    var d'+str(m_index)+'_'+encoding+' = [{label: "'+param_names[0]+'", data: e'+str(m_index)+'_'+encoding+'_'+param_ids[0]+
                        ', bars:{order:0}}, {label: "'+param_names[1]+'", data: e'+str(m_index)+'_'+encoding+'_'+param_ids[1]+', bars:{order:1}}];\n')
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
    ofile.write('    });\n')

    ofile.write('  </script>\n')
    ofile.write('</head>\n')
    ofile.write('<body>\n')
    ofile.write('  <div id="header">\n')
    ofile.write('    <h2>Xpra Performance Results</h2>\n')
    ofile.write('  </div>\n')

    m_index = 0
    for metric in sorted(tests.keys()):
        ofile.write('  <div id="metric_box">\n')
        ofile.write('    <div class="metric_label">' + metric + '</div>\n')

        e_index = 0
        for encoding in sorted(tests[metric].keys()):
            ofile.write('    <div class="container">\n')
            ofile.write('      <div id="placeholder_' + str(m_index) + '_' + str(e_index) + '" class="placeholder"></div>\n')
            ofile.write('    </div>\n')
            e_index += 1

        ofile.write('  </div>\n')
        m_index += 1

    ofile.write('</body>\n')
    ofile.write('</html>\n')
    ofile.close()
    
def col_index(label):
    return headers[label]

def get_value(row, label):
    return row[col_index(label)].strip()
    
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
        if ('display' in param.keys()):
            param_name = param['display']
        param_ids.append(param_id)
        param_names.append(param_name)

    for param in params:
        for rep in range(0, reps):
            file_name = data_dir + '/' + prefix + '_' + param['id'] + '_' + str(rep+1) + '.csv'
            accumulate_values(file_name, rep, param)
    write_html()

if __name__ == "__main__":
    main()

