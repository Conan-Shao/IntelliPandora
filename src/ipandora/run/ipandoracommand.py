# -*- coding: utf-8 -*-
# @Author: Shao Feng
# @File  : ipandoracommand.py
# @Time  : 2024-04-17
import logging
import os
import shutil
import stat
import sys
from os import path
import ipandora
from importlib import import_module

logger = logging.getLogger(__name__)


class CommandError(Exception):
    pass


class PathRemove(object):

    def __init__(self, paths_to_remove: list = None, verbose=1):
        self.paths_to_remove = paths_to_remove or []
        self.verbose = verbose

    def handle(self):
        if self.paths_to_remove:
            if self.verbose >= 2:
                sys.stdout.write("Cleaning up files.\n")
            for path_to_remove in self.paths_to_remove:
                if path.isfile(path_to_remove):
                    os.remove(path_to_remove)
                else:
                    shutil.rmtree(path_to_remove)


class FolderCopy(object):

    def __init__(self, origin_folder=None, target_folder=None, verbose=1):
        self.origin_folder = origin_folder
        self.target_folder = target_folder

        # check folder
        if not origin_folder or not target_folder:
            raise CommandError(
                'origin folder [{}] and target folder [{}] must be '
                'not null.'.format(origin_folder, target_folder))

        self.prefix_length = len(self.origin_folder) + 1
        self.verbose = verbose

    @staticmethod
    def makeDir(dirs=None):
        if dirs and not path.exists(dirs):
            try:
                os.makedirs(dirs)
            except FileExistsError:
                raise CommandError("{} already exists".format(dirs))
            except OSError as e:
                raise CommandError(e)

    @staticmethod
    def makeWriteable(filename):
        if not os.access(filename, os.W_OK):
            st = os.stat(filename)
            new_permissions = stat.S_IMODE(st.st_mode) | stat.S_IWUSR
            os.chmod(filename, new_permissions)

    def handle(self):

        # make sure target folder is exist
        self.makeDir(self.target_folder)

        # copy template file
        for root, dirs, files in os.walk(self.origin_folder):

            path_rest = root[self.prefix_length:]
            if path_rest:
                target_dir = path.join(self.target_folder, path_rest)
                if not path.exists(target_dir):
                    os.mkdir(target_dir)

            for dirname in dirs[:]:
                if dirname.startswith('.') or dirname == '__pycache__':
                    dirs.remove(dirname)

            for filename in files:
                if filename.endswith(('.pyo', '.pyc', '.pyd', '.py.class')):
                    # Ignore some files as they cause various breakages.
                    continue
                old_path = path.join(root, filename)

                real_filename = filename

                # parse new file path name
                new_path = path.join(
                    self.target_folder, path_rest, real_filename)

                if path.exists(new_path):
                    raise CommandError(
                        "{} already exists, please create project"
                        " in a empty dir".format(new_path))

                # do copy work
                shutil.copyfile(old_path, new_path)

                if self.verbose >= 2:
                    logger.info('Create {}'.format(new_path))

                try:
                    shutil.copymode(old_path, new_path)
                    self.makeWriteable(new_path)
                except OSError:
                    sys.stderr.write("Notice: Couldn't set permission on {}. "
                                     "You're probably using an uncommon "
                                     "filesystem.".format(new_path))


class IPandoraCommand(object):
    rewrite_template_suffixes = (('.py-tpl', '.py'),)

    def __init__(self):
        self.verbose = 2
        self.options = None

    def handle_project_cmd(self):

        t_f = self.options.test_framework
        p_n = self.options.project_name
        s_t = self.options.subtype
        self.validate_name(p_n, t_f)

        # parse template folder
        if t_f in ['rf', 'robot-framework']:
            _template_folder_name = 'project_template'
        elif t_f in ['pytest'] and s_t in ['api', 'ui']:
            _template_folder_name = '{tf}_template/{st}'.format(tf=t_f, st=s_t)
        else:
            raise CommandError('test framework not support : runner framework -- {}, '
                               'test type -- {}'.format(t_f, s_t))

        _template_folder_common = 'common_template'

        # make target dir
        top_dir = path.join(os.getcwd(), p_n)
        for _tmp in [self.handle_template(_template_folder_name),
                     self.handle_template(_template_folder_common)]:
            FolderCopy(_tmp, top_dir).handle()

    @classmethod
    def handle_template(cls, subdir):
        return path.join(ipandora.__path__[0], 'conf', subdir)

    @classmethod
    def validate_name(cls, name, app):
        if name is None:
            raise CommandError('you must provide a {app} name'.format(
                app=app,
            ))
        # Check it's a valid directory name.
        # allowed "-" in project name
        if not name.replace('-', '').isidentifier():
            raise CommandError(
                "'{name}' is not a valid {app} name. Please make sure the "
                "name is a valid identifier.".format(
                    name=name,
                    app=app,
                )
            )
        # Check it cannot be imported.
        try:
            import_module(name)
        except ImportError:
            pass
        else:
            raise CommandError(
                "'{name}' conflicts with the name of an existing Python "
                "module and cannot be used as a {app} name. Please try "
                "another name.".format(
                    name=name,
                    app=app,
                )
            )

    def execute(self, options):
        """
        Try to execute this command, performing system checks if needed (as
        controlled by the ``requires_system_checks`` attribute, except if
        force-skipped).
        """
        self.options = options
        if options.verbosity:
            self.verbose = options.verbosity
        if self.options.subcommand == 'project':
            self.handle_project_cmd()
