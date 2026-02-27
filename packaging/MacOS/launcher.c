/**
 * This wrapper is needed because of the way Apple resolves paths (sigh..)
 */
#include <Python.h>
#include <stdlib.h>
#include <stdio.h>

int main(int argc, char *argv[]) {
    if (argc < 3) {
        fprintf(stderr, "usage: %s exe_name module.path [args...]\n", argv[0]);
        return 1;
    }

    const char *exe_name   = argv[1];
    const char *module_str = argv[2];
    int sysargc = 1 + (argc - 3);

    wchar_t **sysargv = PyMem_RawMalloc(sizeof(wchar_t *) * sysargc);
    if (!sysargv) {
        fprintf(stderr, "out of memory\n");
        return 1;
    }
    sysargv[0] = Py_DecodeLocale(exe_name, NULL);
    for (int i = 0; i < argc - 3; i++) {
        sysargv[1 + i] = Py_DecodeLocale(argv[3 + i], NULL);
    }

    PyConfig config;
    PyConfig_InitPythonConfig(&config);
    config.parse_argv = 0;          // don't consume argv[0] as a script name
    PyConfig_SetString(&config, &config.program_name, sysargv[0]);
    PyConfig_SetArgv(&config, sysargc, sysargv);
    Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);

    PyObject *module = PyImport_ImportModule(module_str);
    int ret = 1;
    if (module == NULL) {
        PyErr_Print();
        goto cleanup;
    }

    PyObject *func = PyObject_GetAttrString(module, "main");
    if (func == NULL) {
        PyErr_Print();
        Py_DECREF(module);
        goto cleanup;
    }

    PyObject *sysargv_list = PySys_GetObject("argv");  // borrowed ref
    PyObject *result = PyObject_CallFunction(func, "O", sysargv_list);
    Py_DECREF(func);
    Py_DECREF(module);

    if (result == NULL) {
        if (PyErr_ExceptionMatches(PyExc_SystemExit)) {
            PyObject *exc_type, *exc_value, *exc_tb;
            PyErr_Fetch(&exc_type, &exc_value, &exc_tb);
            PyErr_NormalizeException(&exc_type, &exc_value, &exc_tb);
            PyObject *code = PyObject_GetAttrString(exc_value, "code");
            if (code && PyLong_Check(code))
                ret = (int)PyLong_AsLong(code);
            else
                ret = 0;
            Py_XDECREF(code);
            Py_XDECREF(exc_type);
            Py_XDECREF(exc_value);
            Py_XDECREF(exc_tb);
        } else {
            PyErr_Print();
            ret = 1;
        }
    } else {
        ret = PyLong_Check(result) ? (int)PyLong_AsLong(result) : 0;
        Py_DECREF(result);
    }

cleanup:
    Py_Finalize();
    for (int i = 0; i < sysargc; i++)
        PyMem_RawFree(sysargv[i]);
    PyMem_RawFree(sysargv);
    return ret;
}
