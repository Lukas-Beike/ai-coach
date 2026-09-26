from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from backend.coach import conversation_assembly
from backend.coach.conversation_assembly import CoachConversationAssembly


class CoachConversationAssemblyTests(unittest.TestCase):
    def make_assembly(self):
        manager = Mock(name="database_manager")
        manager_provider = Mock(return_value=manager)
        keys = Mock(name="key_values")
        chats = Mock(name="chat_repository")
        events = Mock(name="state_event_buffer")
        lock = Mock(name="database_lock")
        streams = Mock(name="chat_stream_registry")
        conversation_lock = Mock(name="conversation_lock")
        settings = Mock(name="settings")
        openai = Mock(name="openai_client")
        openai_provider = Mock(return_value=openai)
        utc_now = Mock(return_value="2026-09-26T00:00:00Z")
        uuid_factory = Mock(name="uuid_factory")
        logger = Mock(name="logger")
        profile_service = Mock(name="profile_service")
        model_transport = Mock(name="model_transport")
        default_thinking_level = Mock(name="default_thinking_level")
        assembly = CoachConversationAssembly(
            settings=settings,
            database_manager=manager_provider,
            key_values=keys,
            chat_repository=chats,
            state_event_buffer=events,
            database_lock=lock,
            streams=streams,
            conversation_lock=conversation_lock,
            openai_client=openai_provider,
            utc_now=utc_now,
            uuid_factory=uuid_factory,
            logger=logger,
            profile_service=profile_service,
            model_transport=model_transport,
            default_thinking_level=default_thinking_level,
            default_max_output_tokens=2048,
            json_media_type="application/json",
            max_gemini_inline_image_bytes=lambda: 4096,
        )
        return assembly, {
            "manager": manager,
            "manager_provider": manager_provider,
            "keys": keys,
            "chats": chats,
            "events": events,
            "lock": lock,
            "streams": streams,
            "conversation_lock": conversation_lock,
            "settings": settings,
            "openai": openai,
            "openai_provider": openai_provider,
            "utc_now": utc_now,
            "uuid_factory": uuid_factory,
            "logger": logger,
            "profile_service": profile_service,
            "model_transport": model_transport,
            "default_thinking_level": default_thinking_level,
        }

    def test_construction_is_lazy_and_service_factories_keep_shared_identities(self):
        assembly, dependencies = self.make_assembly()
        dependencies["manager_provider"].assert_not_called()
        dependencies["openai_provider"].assert_not_called()

        with (
            patch.object(conversation_assembly, "CoachMessageService") as message_factory,
            patch.object(conversation_assembly, "CoachConversationHistoryService") as history_factory,
            patch.object(conversation_assembly, "GeminiConversationHistoryService") as gemini_factory,
            patch.object(conversation_assembly, "GeminiLocalChatHistoryService") as local_factory,
        ):
            assembly.message_service()
            assembly.history_service()
            assembly.gemini_history_service()
            assembly.gemini_local_history_service()

        self.assertIs(message_factory.call_args.args[0], dependencies["manager"])
        self.assertIs(message_factory.call_args.args[1], dependencies["chats"])
        self.assertIs(message_factory.call_args.args[2], dependencies["events"])
        self.assertIs(history_factory.call_args.args[1], dependencies["chats"])
        self.assertIs(history_factory.call_args.args[2], dependencies["keys"])
        self.assertIs(history_factory.call_args.args[3], dependencies["lock"])
        self.assertIs(gemini_factory.call_args.args[1], dependencies["keys"])
        self.assertIs(local_factory.call_args.args[1], dependencies["chats"])
        self.assertEqual(local_factory.call_args.kwargs["max_inline_bytes"], 4096)
        self.assertEqual(dependencies["manager_provider"].call_count, 4)

    def test_provision_and_reset_retain_gate_and_stream_owners(self):
        assembly, dependencies = self.make_assembly()
        with (
            patch.object(conversation_assembly, "CoachConversationProvisionService") as provision_factory,
            patch.object(conversation_assembly, "CoachConversationResetService") as reset_factory,
        ):
            assembly.provision_service()
            assembly.reset_service()

        self.assertIs(provision_factory.call_args.args[0], dependencies["settings"])
        self.assertIs(provision_factory.call_args.args[2], dependencies["keys"])
        self.assertIs(provision_factory.call_args.args[3], dependencies["openai"])
        self.assertIs(provision_factory.call_args.args[4], dependencies["lock"])
        self.assertIs(reset_factory.call_args.args[3], dependencies["streams"])
        self.assertIs(reset_factory.call_args.args[4], dependencies["lock"])
        self.assertIs(reset_factory.call_args.args[5], dependencies["conversation_lock"])
        self.assertEqual(dependencies["openai_provider"].call_count, 2)

    def test_dialogue_and_gemini_services_keep_shared_factories_and_lazy_config(self):
        assembly, dependencies = self.make_assembly()
        with (
            patch.object(conversation_assembly, "CoachDialogueReadService") as dialogue,
            patch.object(conversation_assembly, "CoachMessageService") as message,
            patch.object(conversation_assembly, "GeminiConversationResponseService") as gemini,
        ):
            assembly.dialogue_read_service()
            assembly.gemini_conversation_response_service()

        self.assertIs(dialogue.call_args.args[0], dependencies["manager"])
        self.assertIs(dialogue.call_args.args[1], message.return_value)
        self.assertIs(dialogue.call_args.args[3], dependencies["profile_service"].return_value)
        self.assertEqual(dependencies["default_thinking_level"].call_count, 1)
        self.assertEqual(dependencies["manager_provider"].call_count, 7)
        self.assertEqual(dependencies["model_transport"].gemini_json_client.call_count, 1)
        self.assertEqual(dependencies["model_transport"].gemini_stream_client.call_count, 1)
        self.assertIsNotNone(gemini.call_args)


if __name__ == "__main__":
    unittest.main()
