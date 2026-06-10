import http.client
import threading
import unittest

from proxyscope.app.config.runtime import RuntimeConfig
from proxyscope.app.editing.modifier import ResponseModifierService
from proxyscope.app.logging.observability import RuntimeEventDispatcher
from proxyscope.app.logging.request_response import RequestResponseRecorder
from proxyscope.app.runtime.context import create_proxy_runtime_context
from proxyscope.app.runtime.journal import RequestJournal
from proxyscope.policies.engine import PolicyEngine
from proxyscope.proxy.runtime import (
    CachePolicy,
    ExchangeRecorder,
    PolicyEvaluator,
    ResponseTransformer,
    RuntimeEventSink,
)
from proxyscope.proxy.server import create_server


class TestRuntimePortContracts(unittest.TestCase):
    def test_app_adapters_implement_runtime_ports(self) -> None:
        config = RuntimeConfig()
        journal = RequestJournal()
        modifier = ResponseModifierService(policy_evaluator=PolicyEngine(config.policy_repository))
        recorder = RequestResponseRecorder(runtime_config=config, request_journal=journal)
        events = RuntimeEventDispatcher()

        self.assertIsInstance(PolicyEngine(config.policy_repository), PolicyEvaluator)
        self.assertIsInstance(config, CachePolicy)
        self.assertIsInstance(recorder, ExchangeRecorder)
        self.assertIsInstance(modifier, ResponseTransformer)
        self.assertIsInstance(events, RuntimeEventSink)


class TestRuntimeContextIsolation(unittest.TestCase):
    def test_two_running_proxy_instances_keep_policies_and_journals_isolated(self) -> None:
        contexts = []
        journals = []
        servers = []
        threads = []
        for body in (b"first-runtime", b"second-runtime"):
            config = RuntimeConfig()
            config.add_static_response_rule(
                url="http://example.com/isolation",
                headers={"Content-Type": "text/plain"},
                body=body,
                method="GET",
            )
            journal = RequestJournal()
            context = create_proxy_runtime_context(runtime_config=config, request_journal=journal)
            server = create_server("127.0.0.1", 0, runtime_context=context, auto_enable_mitm=False)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            contexts.append(context)
            journals.append(journal)
            servers.append(server)
            threads.append(thread)

        try:
            responses = []
            for server in servers:
                host, port = server.server_address
                connection = http.client.HTTPConnection(host, port, timeout=2)
                connection.request("GET", "http://example.com/isolation", headers={"Host": "example.com"})
                response = connection.getresponse()
                responses.append(response.read())
                connection.close()

            self.assertEqual(responses, [b"first-runtime", b"second-runtime"])
            self.assertEqual(len(journals[0].list_entries()), 1)
            self.assertEqual(len(journals[1].list_entries()), 1)
            self.assertIsNot(contexts[0].policy_evaluator, contexts[1].policy_evaluator)
            self.assertIsNot(contexts[0].exchange_recorder, contexts[1].exchange_recorder)
        finally:
            for server in servers:
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
