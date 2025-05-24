import time
import re
import psutil
import os
import threading

import jpype

from jpype import java


class PyJClass:
    def __init__(self, class_mappings):
        self.mappings = class_mappings
        class_path = self.mappings['obfuscated_class_name']
        self.jclass = jpype.JClass(class_path)
        self.clazz = self.jclass.class_
        self.instance = None

    def __getattr__(self, name):
        if name in self.mappings['fields']:
            obfuscated_field_name = self.mappings['fields'].get(name)
            if obfuscated_field_name:
                field = self.clazz.getDeclaredField(obfuscated_field_name)
                field.setAccessible(True)
                if not self.instance:
                    return field
                return field.get(self.instance)

        if name in self.mappings['methods']:
            obfuscated_method_name = self.mappings['methods'].get(name)
            if obfuscated_method_name:
                methods = [
                    method for method in self.clazz.getDeclaredMethods()
                    if method.getName() == obfuscated_method_name
                ]

                def find_matching_method(num_params=0, param_types=None, return_type="any"):
                    filtered_methods = [
                        method for method in methods
                        if (num_params == 0 or method.getParameterCount() == num_params)
                    ]

                    if param_types:
                        def match_param_types(method):
                            method_param_types = [str(t.getName()) for t in method.getParameterTypes()]
                            return method_param_types == param_types

                        filtered_methods = [method for method in filtered_methods if match_param_types(method)]

                    if return_type != "any":
                        filtered_methods = [
                            method for method in filtered_methods
                            if str(method.getReturnType().getName()) == return_type
                        ]

                    if not filtered_methods:
                        raise AttributeError(f"Нет подходящего метода для '{name}' с указанными параметрами.")

                    return filtered_methods[0]

                def method_handler(*args, num_params=0, param_types=None, return_type="any"):
                    method = find_matching_method(num_params=num_params, param_types=param_types, return_type=return_type)
                    method.setAccessible(True)
                    return method.invoke(self.instance, *args)

                return method_handler


        raise AttributeError(f"'{self.jclass}' has no attribute '{name}'")

    def __setattr__(self, name, value):
        if name in ('mappings', 'jclass', 'clazz', 'instance'):
            super().__setattr__(name, value)
        elif name in self.mappings.get('fields', {}):
            obfuscated_field_name = self.mappings['fields'].get(name)
            if obfuscated_field_name:
                field = self.clazz.getDeclaredField(obfuscated_field_name)
                field.setAccessible(True)
                if not self.instance:
                    raise AttributeError("Instance is not set for setting field values.")
                field.set(self.instance, value)
        else:
            super().__setattr__(name, value)

    def set_instance(self, instance):
        self.instance = instance

class PyJMine:
    def __init__(self):
        self.version = None

    def _find_java_process_info(self):
        global cmdline_list
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['name'] == 'javaw.exe' and proc.info['cmdline']:
                    cmdline_list = proc.info['cmdline']
                    javaw_path = os.path.join(cmdline_list[0])
                    jvm_args = []
                    classpath = None
                    run_args = []
                    cmd_line_str = ' '.join(cmdline_list)

                    for arg in cmdline_list:
                        if arg.startswith('-X') or arg.startswith('-Djava'):
                            jvm_args.append(arg)

                    classpath = cmdline_list[cmdline_list.index('-cp') + 1]

                    for arg in cmdline_list:
                        if '--' in arg:
                            run_args.append(arg)
                            arg_value = cmdline_list[cmdline_list.index(arg) + 1]
                            run_args.append(arg_value)

                    run_class = cmdline_list[cmdline_list.index('--username') - 1]
                    version = run_args[run_args.index('--version') + 1]
                    self.version = re.sub(r'[^0-9.]', '', version)

                    return proc.info['pid'], jvm_args, classpath, run_class, run_args, version
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return None, None, None, None, None, None

    def init(self, custom_jdk=None):
        pid, jvm_args, classpath, run_class, run_args, version = self._find_java_process_info()
        if pid:
            if not custom_jdk:
                jpype.startJVM(*jvm_args, classpath=classpath)
            else:
                jpype.startJVM(custom_jdk, *jvm_args, classpath=classpath)

            MainClass = jpype.JClass(run_class)

            StringArray = jpype.JArray(java.lang.String)
            java_args = StringArray(run_args)

            process = psutil.Process(pid)
            process.terminate()

            threading.Thread(target=MainClass.main, args=(java_args,)).start()
        else:
            raise Exception('Minecraft not runned!')

    def get_class(self, class_mappings):
        return PyJClass(class_mappings)
