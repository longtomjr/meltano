import pytest
import requests
import requests_mock
import json
import yaml
import copy
from contextlib import contextmanager
from unittest import mock

import meltano.core.bundle as bundle

from meltano.core.project_settings_service import ProjectSettingsService
from meltano.core.plugin import (
    PluginType,
    PluginDefinition,
    Variant,
    VariantNotFoundError,
    ProjectPlugin,
)
from meltano.core.plugin_discovery_service import (
    DiscoveryFile,
    PluginDiscoveryService,
    VERSION,
)
from meltano.core.config_service import PluginAlreadyAddedException
from meltano.core.behavior.versioned import IncompatibleVersionError


@pytest.fixture(scope="class")
def project(project):
    project.root_dir("discovery.yml").unlink()
    return project


@pytest.fixture
def subject(plugin_discovery_service):
    return plugin_discovery_service


@pytest.fixture
def discovery_url_mock(subject):
    with requests_mock.Mocker() as m:
        m.get(subject.discovery_url, status_code=418)

        yield


@pytest.fixture(scope="class")
def tap_covid_19(project_add_service):
    try:
        plugin = ProjectPlugin(
            PluginType.EXTRACTORS,
            "tap-covid-19",
            namespace="tap-covid_19",
            pip_url="tap-covid-19",
            executable="tap-covid-19",
        )
        return project_add_service.add_plugin(plugin)
    except PluginAlreadyAddedException as err:
        return err.plugin


@pytest.mark.usefixtures("discovery_url_mock")
class TestPluginDiscoveryService:
    @pytest.mark.meta
    def test_discovery_url_mock(self, subject):
        assert requests.get(subject.discovery_url).status_code == 418

    @pytest.fixture
    def discovery_yaml(self, subject):
        """Disable the discovery mock"""
        with subject.project.root_dir("discovery.yml").open("w") as d:
            yaml.dump(subject._discovery, d)

        subject._discovery = None

    def test_plugins(self, subject):
        plugins = list(subject.plugins())

        assert subject.discovery
        assert len(plugins) >= 6

    def test_plugins_unknown(self, subject):
        plugins = list(subject.plugins())
        assert len(plugins) >= 6

    def test_plugins_custom(self, subject, tap_covid_19):
        plugins = list(subject.plugins())

        assert tap_covid_19 in plugins

    def test_find_definition(self, subject):
        # If no variant is specified,
        # defaults to the first variant
        plugin_def = subject.find_definition(PluginType.EXTRACTORS, "tap-mock")
        assert plugin_def.type == PluginType.EXTRACTORS
        assert plugin_def.name == "tap-mock"
        assert plugin_def.current_variant == plugin_def.variants[0]

        plugin_def = subject.find_definition(
            PluginType.EXTRACTORS, "tap-mock", variant="singer-io"
        )
        assert plugin_def.type == PluginType.EXTRACTORS
        assert plugin_def.name == "tap-mock"
        assert plugin_def.current_variant_name == "singer-io"

        plugin_def = subject.find_definition(
            PluginType.EXTRACTORS, "tap-mock", variant="meltano"
        )
        assert plugin_def.type == PluginType.EXTRACTORS
        assert plugin_def.name == "tap-mock"
        assert plugin_def.current_variant_name == "meltano"

        plugin_def = subject.find_definition(
            PluginType.EXTRACTORS, "tap-mock", variant=Variant.ORIGINAL_NAME
        )
        assert plugin_def.type == PluginType.EXTRACTORS
        assert plugin_def.name == "tap-mock"
        assert plugin_def.current_variant_name == "singer-io"

        with pytest.raises(VariantNotFoundError):
            plugin_def = subject.find_definition(
                PluginType.EXTRACTORS, "tap-mock", variant="unknown"
            )

    def test_get_definition(self, subject):
        # If no variant is set on the project plugin,
        # defaults to the original variant
        project_plugin = ProjectPlugin(PluginType.EXTRACTORS, "tap-mock")
        plugin_def = subject.get_definition(project_plugin)
        assert plugin_def.type == PluginType.EXTRACTORS
        assert plugin_def.name == "tap-mock"
        assert plugin_def.current_variant_name == "singer-io"
        assert plugin_def.current_variant.original

        project_plugin = ProjectPlugin(
            PluginType.EXTRACTORS, "tap-mock", variant="meltano"
        )
        plugin_def = subject.get_definition(project_plugin)
        assert plugin_def.type == PluginType.EXTRACTORS
        assert plugin_def.name == "tap-mock"
        assert plugin_def.current_variant_name == "meltano"

        project_plugin = ProjectPlugin(
            PluginType.EXTRACTORS, "tap-mock", variant="singer-io"
        )
        plugin_def = subject.get_definition(project_plugin)
        assert plugin_def.type == PluginType.EXTRACTORS
        assert plugin_def.name == "tap-mock"
        assert plugin_def.current_variant_name == "singer-io"

        project_plugin = ProjectPlugin(
            PluginType.EXTRACTORS, "tap-mock", variant=Variant.ORIGINAL_NAME
        )
        plugin_def = subject.get_definition(project_plugin)
        assert plugin_def.type == PluginType.EXTRACTORS
        assert plugin_def.name == "tap-mock"
        assert plugin_def.current_variant_name == "singer-io"

        project_plugin = ProjectPlugin(
            PluginType.EXTRACTORS, "tap-mock", variant="unknown"
        )
        with pytest.raises(VariantNotFoundError):
            subject.get_definition(project_plugin)

    @pytest.mark.usefixtures("discovery_yaml")
    def test_discovery_yaml(self, subject):
        plugins_by_type = subject.plugins_by_type()

        # raw yaml load
        for plugin_type, raw_plugin_defs in subject._discovery:
            if not PluginType.value_exists(plugin_type):
                continue

            plugin_type = PluginType(plugin_type)

            plugin_defs = plugins_by_type[plugin_type]
            plugin_names = [plugin.name for plugin in plugins_by_type[plugin_type]]

            for raw_plugin_def in raw_plugin_defs:
                assert raw_plugin_def["name"] in plugin_names


class TestPluginDiscoveryServiceDiscoveryManifest:
    def build_discovery_yaml(self, namespace, version=VERSION):
        return {
            "version": version,
            "extractors": [{"name": f"{namespace}-test", "namespace": namespace}],
        }

    def assert_discovery_yaml(self, subject, discovery_yaml):
        subject._discovery = None
        assert (
            subject.discovery.extractors[0].namespace
            == discovery_yaml["extractors"][0]["namespace"]
        )

    @contextmanager
    def use_local_discovery(self, discovery_yaml, subject):
        local_discovery_path = subject.project.root_dir("discovery.yml")
        with local_discovery_path.open("w") as local_discovery:
            yaml.dump(discovery_yaml, local_discovery)

        yield discovery_yaml

        local_discovery_path.unlink()

    @contextmanager
    def use_remote_discovery(self, discovery_yaml, subject):
        with requests_mock.Mocker() as m:
            m.get(subject.discovery_url, text=yaml.dump(discovery_yaml))

            yield discovery_yaml

    @contextmanager
    def use_cached_discovery(self, discovery_yaml, subject):
        with subject.cached_discovery_file.open("w") as cached_discovery:
            yaml.dump(discovery_yaml, cached_discovery)

        yield discovery_yaml

        subject.cached_discovery_file.unlink()

    @pytest.fixture
    def local_discovery(self, subject):
        with self.use_local_discovery(
            self.build_discovery_yaml("local"), subject
        ) as discovery_yaml:
            yield discovery_yaml

    @pytest.fixture
    def incompatible_local_discovery(self, subject):
        with self.use_local_discovery(
            self.build_discovery_yaml("local", version=VERSION - 1), subject
        ) as discovery_yaml:
            yield discovery_yaml

    @pytest.fixture
    def remote_discovery(self, project, subject):
        with self.use_remote_discovery(
            self.build_discovery_yaml("remote"), subject
        ) as discovery_yaml:
            yield discovery_yaml

    @pytest.fixture
    def incompatible_remote_discovery(self, subject):
        with self.use_remote_discovery(
            self.build_discovery_yaml("remote", version=VERSION + 1), subject
        ) as discovery_yaml:
            yield discovery_yaml

    @pytest.fixture
    def disabled_remote_discovery(self, project):
        ProjectSettingsService(project).set("discovery_url", "false")

    @pytest.fixture
    def cached_discovery(self, subject):
        with self.use_cached_discovery(
            self.build_discovery_yaml("cached"), subject
        ) as discovery_yaml:
            yield discovery_yaml

    @pytest.fixture
    def invalid_cached_discovery(self, subject):
        with self.use_cached_discovery(
            {"version": VERSION, "invalid_key": "value"}, subject
        ) as discovery_yaml:
            yield discovery_yaml

    @pytest.fixture
    def bundled_discovery(self):
        with bundle.find("discovery.yml").open() as bundled_discovery:
            return yaml.safe_load(bundled_discovery)

    def test_local_discovery(self, subject, local_discovery):
        self.assert_discovery_yaml(subject, local_discovery)

        assert not subject.cached_discovery_file.exists()

    def test_incompatible_local_discovery(
        self, subject, incompatible_local_discovery, remote_discovery
    ):
        self.assert_discovery_yaml(subject, remote_discovery)

    def test_remote_discovery(self, subject, remote_discovery):
        self.assert_discovery_yaml(subject, remote_discovery)

        assert subject.cached_discovery_file.exists()

    def test_incompatible_remote_discovery(
        self, subject, incompatible_remote_discovery, cached_discovery
    ):
        self.assert_discovery_yaml(subject, cached_discovery)

    def test_disabled_remote_discovery(
        self, subject, disabled_remote_discovery, cached_discovery
    ):
        self.assert_discovery_yaml(subject, cached_discovery)

    def test_cached_discovery(
        self, subject, incompatible_remote_discovery, cached_discovery
    ):
        self.assert_discovery_yaml(subject, cached_discovery)

    def test_invalid_cached_discovery(
        self,
        subject,
        incompatible_remote_discovery,
        invalid_cached_discovery,
        bundled_discovery,
    ):
        self.assert_discovery_yaml(subject, bundled_discovery)

    def test_bundled_discovery(
        self, subject, incompatible_remote_discovery, bundled_discovery
    ):
        self.assert_discovery_yaml(subject, bundled_discovery)

        assert subject.cached_discovery_file.exists()
