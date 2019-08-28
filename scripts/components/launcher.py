import datetime
import multiprocessing
import subprocess
import tempfile

from aux.common import *
from components.component import Component
from components.coverage_processor import Coverage
from models.verification_result import *

DEFAULT_CIL_DIR = "cil"
DEFAULT_MAIN_DIR = "main"
DEFAULT_LAUNCHES_DIR = "launches"
DEFAULT_SOURCE_PATCHES_DIR = "patches/sources"
DEFAULT_PREPARATION_PATCHES_DIR = "patches/preparation"
DEFAULT_ENTRYPOINTS_DIR = "entrypoints"
DEFAULT_RULES_DIR = "rules"
DEFAULT_PLUGIN_DIR = "plugin"

DEFAULT_BACKUP_PREFIX = "backup_"

TAG_LIMIT_MEMORY = "memory size"
TAG_LIMIT_CPU_TIME = "CPU time"
TAG_LIMIT_CPU_CORES = "number of cores"
TAG_CACHED = "cached"
TAG_BRANCH = "branch"
TAG_PATCH = "patches"
TAG_BUILD_PATCH = "build patch"
TAG_MAX_COVERAGE = "max"
TAG_CALLERS = "callers"
TAG_COMMITS = "commits"
TAG_BACKUP_WRITE = "backup write"
TAG_BACKUP_READ = "backup read"
TAG_BENCHMARK_ARGS = "benchmark args"
TAG_PARALLEL_LAUNCHES = "parallel launches"
TAG_RESOURCE_LIMITATIONS = "resource limits"
TAG_PROCESSES = "processes"
TAG_SCHEDULER = "scheduler"
TAG_CLOUD = "cloud"
TAG_CLOUD_MASTER = "master"
TAG_CLOUD_PRIORITY = "priority"
TAG_UPLOADER_UPLOAD_RESULTS = "upload results"
TAG_UPLOADER_IDENTIFIER = "identifier"
TAG_UPLOADER_SERVER = "server"
TAG_UPLOADER_USER = "user"
TAG_UPLOADER_PASSWORD = "password"
TAG_UPLOADER_PARENT_ID = "parent id"
TAG_SKIP = "skip"
TAG_STATISTICS_TIME = "statistics time"
TAG_BUILD_CONFIG = "build config"
TAG_ID = "id"
TAG_REPOSITORY = "repository"
TAG_NAME = "name"
TAG_VERIFIER_OPTIONS = "verifier options"
TAG_EXPORT_HTML_ERROR_TRACES = "standalone error traces"

TIMESTAMP_PATTERN = "<timestamp>"
RUNDEFINITION_PATTERN = "<rundefinition>"
COMMIT_PATTERN = "<commit>"

SCHEDULER_CLOUD = "cloud"
SCHEDULER_LOCAL = "local"
SCHEDULERS = [SCHEDULER_CLOUD, SCHEDULER_LOCAL]

CLOUD_PRIORITIES = ["IDLE", "LOW", "HIGH", "URGENT"]
DEFAULT_CLOUD_PRIORITY = "LOW"
CLOUD_BENCHMARK_LOG = "benchmark_log.txt"

HARDCODED_RACES_OUTPUT_DIR = "output"

ROUND_DIGITS = 9  # nanoseconds.

DEFAULT_TIME_FOR_STATISTICS = 0  # By default we do not allocate time for printing statistics.

VERIFIER_OPTIONS_NOT_OPTIMIZED = [
    "cpa.functionpointer.ignoreUnknownFunctionPointerCalls=false",
]

VERIFIER_FILES_DIR = "verifier_files"
VERIFIER_OPTIONS_DIR = "options"
VERIFIER_PROPERTIES_DIR = "properties"

VERIFIER_OPTIONS_COMMON = "common"

SOURCE_QUEUE_BUILDER_RESOURCES = "builder resources"
SOURCE_QUEUE_QUALIFIER_RESOURCES = "qualifier resources"
SOURCE_QUEUE_FILES = "files"
SOURCE_QUEUE_FUNCTIONS = "functions"
SOURCE_QUEUE_RESULTS = "results"

TAG_ENTRYPOINTS_DESC = "entrypoints desc"
TAG_PREPARATION_CONFIG = "preparation config"
DEFAULT_PREPARATION_CONFIG = "conf.json"
DEFAULT_PROPERTY_MEMSAFETY = "properties/memsafety.spc"
DEFAULT_PROPERTY_UNREACHABILITY = "properties/unreachability.spc"


class Launcher(Component):
    """
    Main component, which creates verification tasks for the given system, launches them and processes results.
    """
    def __init__(self, name: str, config_file: str):
        self.config_file = os.path.basename(config_file).replace(JSON_EXTENSION, "")
        if os.path.exists(config_file):
            with open(config_file, errors='ignore') as data_file:
                config = json.load(data_file)
        else:
            config = {
                TAG_DIRS: {
                    TAG_DIRS_RESULTS: DEFAULT_RESULTS_DIR,
                    TAG_DIRS_WORK: DEFAULT_WORK_DIR
                }
            }

        super(Launcher, self).__init__(name, config)

        # Since Launcher does not produce a lot of output and any of its failure is fatal, we can put in on stdout.
        if self.debug:
            self.output_desc = sys.stdout
        else:
            self.output_desc = subprocess.DEVNULL

        # Remember some useful directories.
        self.root_dir = os.getcwd()  # By default tool-set is run from this directory.
        self.work_dir = os.path.abspath(self.config[TAG_DIRS][TAG_DIRS_WORK])
        self.results_dir = os.path.abspath(self.config[TAG_DIRS][TAG_DIRS_RESULTS])
        if not os.path.exists(self.results_dir):
            os.makedirs(self.results_dir, exist_ok=True)

        if self.config.get(TAG_EXPORT_HTML_ERROR_TRACES, False):
            self.result_dir_et = os.path.abspath(os.path.join(self.config[TAG_DIRS][TAG_DIRS_RESULTS],
                                                              self._get_result_file_prefix()))
        else:
            self.result_dir_et = None
        self.install_dir = os.path.join(self.root_dir, DEFAULT_INSTALL_DIR)

        self.cpu_cores = multiprocessing.cpu_count()

        self.backup = None  # File, in which backup copy will be placed during verification.

        # Defines type of scheduler.
        self.scheduler = self.component_config.get(TAG_SCHEDULER)
        if not self.scheduler or self.scheduler not in SCHEDULERS:
            self.logger.error("Scheduler '{}' is not known. Choose from {}".format(self.scheduler, SCHEDULERS))
            exit(1)
        self.benchmark_args = self.component_config.get(TAG_BENCHMARK_ARGS, "")
        if self.scheduler == SCHEDULER_CLOUD:
            cloud_master = self.config.get(TAG_CLOUD, {}).get(TAG_CLOUD_MASTER)
            cloud_priority = self.config.get(TAG_CLOUD, {}).get(TAG_CLOUD_PRIORITY, DEFAULT_CLOUD_PRIORITY)
            self.benchmark_args = "{} --cloud --cloudMaster {} --cloudPriority {}".\
                format(self.benchmark_args, cloud_master, cloud_priority)
        self.job_name_suffix = ""

    def _copy_result_files(self, files: list, group_directory: str) -> str:
        launch_dir = os.path.abspath(tempfile.mkdtemp(dir=group_directory))
        for file in files:
            if file.endswith(".files"):
                for root, dirs, files_in in os.walk(file):
                    for name in files_in:
                        file = os.path.join(root, name)
                        shutil.copy(file, launch_dir)
            if file.endswith(".log"):
                shutil.copy(file, os.path.join(launch_dir, LOG_FILE))
        return launch_dir

    def _process_coverage(self, result, launch_directory, source_dirs: list, default_source_file=None):
        cov = Coverage(self, default_source_file=default_source_file)
        cov_queue = multiprocessing.Queue()
        cov_process = multiprocessing.Process(target=cov.compute_coverage, name="coverage_{}".format(result.get_name()),
                                              args=(source_dirs, launch_directory, cov_queue))
        cov_process.start()
        cov_process.join()  # Wait since we are already in parallel threads for each launch.
        if not cov_process.exitcode:
            if cov_queue.qsize():
                data = cov_queue.get()
                result.cov_funcs = data.get(TAG_COVERAGE_FUNCS, 0.0)
                result.cov_lines = data.get(TAG_COVERAGE_LINES, 0.0)
                result.coverage_resources[TAG_CPU_TIME] = data.get(TAG_CPU_TIME, 0.0)
                result.coverage_resources[TAG_WALL_TIME] = data.get(TAG_WALL_TIME, 0.0)
                result.coverage_resources[TAG_MEMORY_USAGE] = data.get(TAG_MEMORY_USAGE, 0)
        else:
            self.logger.warning("Coverage was not computed for {} and entry-point {}".
                                format(result.id, result.entrypoint))

    def _get_from_queue_into_list(self, queue, result_list):
        while not queue.empty():
            launch = queue.get()
            result_list.append(launch)
            if self.backup:
                with open(self.backup, "a") as f_report:
                    f_report.write(str(launch) + "\n")
        return result_list

    def _get_result_file_prefix(self):
        return self.config_file + "_" + datetime.datetime.fromtimestamp(time.time()).strftime('%Y_%m_%d_%H_%M_%S')

    def _upload_results(self, uploader_config, result_file):
        server = uploader_config.get(TAG_UPLOADER_SERVER)
        identifier = uploader_config.get(TAG_UPLOADER_IDENTIFIER)
        user = uploader_config.get(TAG_UPLOADER_USER)
        password = uploader_config.get(TAG_UPLOADER_PASSWORD)
        is_parent = uploader_config.get(TAG_UPLOADER_PARENT_ID, False)
        predefined_name = uploader_config.get(TAG_NAME, None)
        if not server:
            self.logger.error("Server was not provided for uploading results, skipping it.")
            return
        if not identifier:
            self.logger.error("Job identifier was not provided for uploading results, skipping it.")
            return
        if not user:
            self.logger.error("User name was not provided for uploading results, skipping it.")
            return
        self.logger.info("Uploading results into server {} with identifier {}".format(server, identifier))
        uploader = self.get_tool_path(DEFAULT_TOOL_PATH[UPLOADER])
        uploader_python_path = os.path.abspath(os.path.join(os.path.dirname(uploader), os.path.pardir))
        commits = self.config.get(TAG_COMMITS)
        if commits:
            commit = commits[0]
            res = re.search(r'(\w+)\.\.(\w+)', commit)
            if res:
                commit = res.group(2)
                commits = commit[:7]
        timestamp = datetime.datetime.fromtimestamp(time.time()).strftime('%Y_%m_%d_%H_%M_%S')
        if predefined_name:
            job_name = predefined_name.replace(TIMESTAMP_PATTERN, timestamp)
            job_name = job_name.replace(RUNDEFINITION_PATTERN, self.job_name_suffix)
            job_name = job_name.replace(COMMIT_PATTERN, str(commits))
        elif commits:
            job_name = "{}: {} ({})".format(self.config_file, commits, timestamp)
        else:
            job_name = "{} ({})".format(self.config_file, timestamp)
        self.logger.debug("Using name '{}' for uploaded report".format(job_name))
        command = "PYTHONPATH={} {} {} --host='{}' --username='{}' --password='{}' --archive='{}' --name='{}'". \
            format(uploader_python_path, uploader, identifier, server, user, password, result_file, job_name)
        if is_parent:
            command = "{} --copy".format(command)
        try:
            subprocess.check_call(command, shell=True)
        except:
            self.logger.warning("Error on uploading of report archive '{}' via command '{}':\n".
                                format(result_file, command), exc_info=True)
        self.logger.info("Results were successfully uploaded into the server: {}/jobs".format(server))

    def _get_none_rule_key(self, verification_result: VerificationResults):
        return "{0}_{1}".format(verification_result.id, verification_result.entrypoint)

    def _print_launches_report(self, file_name: str, report_resources: str, results: list, cov_lines: dict = None,
                               cov_funcs: dict = None):
        self.logger.info("Preparing report on launches into file: '{}'".format(file_name))
        with open(file_name, "w") as f_report, open(report_resources, "w") as f_resources:
            # Write headers.
            f_report.write("Subsystem;Rule;Entrypoint;Verdict;Termination;CPU;Wall;Memory;Relevancy;"
                           "Traces;Filtered traces;Work dir;Cov lines;Cov funcs;MEA time\n")
            f_resources.write("Counter;" + ";".join(ADDITIONAL_RESOURCES) + "\n")
            counter = 1
            for result in results:
                # Add coverage information.
                if result.verdict == VERDICT_SAFE and not result.rule == RULE_COVERAGE:
                    key = self._get_none_rule_key(result)
                    if not result.cov_lines and cov_lines:
                        result.cov_lines = cov_lines.get(key, 0.0)
                    if not result.cov_funcs and cov_funcs:
                        result.cov_funcs = cov_funcs.get(key, 0.0)
                f_report.write(str(result) + "\n")
                f_resources.write("{};".format(counter) + result.print_resources() + "\n")
                counter += 1

    def _get_results_names(self) -> tuple:
        reports_prefix = self._get_result_file_prefix()
        report_launches = os.path.join(self.results_dir, "report_launches_{0}.csv".format(reports_prefix))
        result_archive = os.path.join(self.results_dir, "results_{0}.zip".format(reports_prefix))
        report_components = os.path.join(self.results_dir, "report_components_{0}.csv".format(reports_prefix))
        short_report = os.path.join(self.results_dir, "short_report_{0}.csv".format(reports_prefix))
        report_resources = os.path.join(self.results_dir, "report_resources_{0}.csv".format(reports_prefix))
        return report_launches, result_archive, report_components, short_report, report_resources
