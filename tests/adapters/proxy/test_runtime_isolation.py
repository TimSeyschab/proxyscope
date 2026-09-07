import http.client
import threading
import unittest

from proxyscope.adapters.proxy.server import create_server
from proxyscope.application.journal import RequestJournal
from proxyscope.bootstrap.composition import create_proxy_runtime_context
from tests.support.runtime_context import RuntimeTestContext, processing_dependencies


class TestRuntimeContextIsolation(unittest.TestCase):
    def test_two_running_proxy_instances_keep_rules_and_journals_isolated(self) -> None:
        contexts = []
        journals = []
        servers = []
        threads = []
        for body in (b"first-runtime", b"second-runtime"):
            config = RuntimeTestContext()
            config.add_static_response_rule(
                url="http://example.com/isolation",
                headers={"Content-Type": "text/plain"},
                body=body,
                method="GET",
            )
            journal = RequestJournal()
            context = create_proxy_runtime_context(**processing_dependencies(config), request_journal=journal)
            server = create_server("127.0.0.1", 0, runtime_context=context)
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
            self.assertIsNot(contexts[0].exchange_pipeline, contexts[1].exchange_pipeline)
            self.assertIsNot(contexts[0].exchange_recorder, contexts[1].exchange_recorder)
        finally:
            for server in servers:
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=2)
