# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""
Memory Isolation Handler - 处理记忆的隔离机制

根据 account namespace policy 和 session 参与者列表，
计算记忆的写入目录并校验 role_id。
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from openviking.message import Message
from openviking.server.identity import AccountNamespacePolicy, RequestContext
from openviking_cli.session.user_id import UserIdentifier
from openviking_cli.utils import get_logger

logger = get_logger(__name__)




@dataclass
class RoleScope:
    """Role 作用范围 - 从 messages 推断的可访问范围"""

    user_ids: List[str]  # 参与者中的 user_id 列表
    agent_ids: List[str]  # 参与者中的 agent_id 列表


@dataclass
class MemoryTarget:
    """记忆写入目标"""

    uri: str  # 完整的 canonical URI
    user_space: str  # 用于 URI 生成
    agent_space: str  # 用于 URI 生成

class MemoryIsolationHandler:
    """Memory isolation handler."""

    def __init__(self, ctx: RequestContext, extract_context: Any):
        self.ctx = ctx
        self._extract_context = extract_context


    def get_read_scope(self) -> RoleScope:
        user_ids = set()
        agent_ids = set()

        messages = self._extract_context.messages if self._extract_context else []
        for msg in messages:
            role = msg.role
            role_id = msg.role_id
            if not role_id:
                continue
            if role == "user":
                user_ids.add(role_id)
            elif role == "assistant":
                agent_ids.add(role_id)

        return RoleScope(
            user_ids=list(user_ids),
            agent_ids=list(agent_ids),
        )

    def needs_explicit_user_id(
        self,
        schema_directory: str,
        isolate_agent_scope_by_user: bool,
        has_ranges: bool,
    ) -> bool:
        """
        判断某个 memory_type 是否需要 LLM 明确输出 user_id。

        Args:
            schema_directory: schema 的 directory 模板
            isolate_agent_scope_by_user: policy 配置
            has_ranges: operation 是否有 ranges 字段

        Returns:
            True 表示需要 LLM 输出 user_id
        """
        # 有 ranges 就不需要
        if has_ranges:
            return False

        depends_on_user_space = "{{ user_space }}" in schema_directory
        depends_on_agent_space = "{{ agent_space }}" in schema_directory

        # 如果依赖 user_space，必须输出 user_id
        if depends_on_user_space:
            return True

        # 如果依赖 agent_space 且 isolate_agent_scope_by_user=True，需要 user_id
        if depends_on_agent_space and isolate_agent_scope_by_user:
            return True

        return False

    def needs_explicit_agent_id(
        self,
        schema_directory: str,
        isolate_user_scope_by_agent: bool,
    ) -> bool:
        """
        判断某个 memory_type 是否需要 LLM 明确输出 agent_id。
        """
        depends_on_user_space = "{{ user_space }}" in schema_directory
        depends_on_agent_space = "{{ agent_space }}" in schema_directory

        # 如果依赖 agent_space，必须输出 agent_id
        if depends_on_agent_space:
            return True

        # 如果依赖 user_space 且 isolate_user_scope_by_agent=True，需要 agent_id
        if depends_on_user_space and isolate_user_scope_by_agent:
            return True

        return False

    def validate_role_id(self, role_id: str, role_type: str) -> bool:
        """
        校验 role_id 是否在参与者范围内。
        - role_type="user" 时，校验 role_id 在 participant user_ids 中
        - role_type="agent" 时，校验 role_id 在 participant agent_ids 中
        """
        if role_type == "user":
            return role_id in self.get_participant_user_ids()
        else:
            return role_id in self.get_participant_agent_ids()

    def get_valid_role_ids(self, role_type: str) -> List[str]:
        """获取指定类型的有效 role_id 列表"""
        if role_type == "user":
            return self.get_participant_user_ids()
        else:
            return self.get_participant_agent_ids()

    def get_participant_user_ids(self) -> List[str]:
        """获取参与者中的 user_id 列表"""
        return self.get_read_scope().user_ids

    def get_participant_agent_ids(self) -> List[str]:
        """获取参与者中的 agent_id 列表"""
        return self.get_read_scope().agent_ids

    def fulfill_user_id_and_agent_id(
        self, item_dict: Dict[str, Any], role_scope: Optional[RoleScope] = None
    ) -> None:
        """
        填充 item_dict 中的 user_id 和 agent_id 字段。

        如果 item_dict 中没有这些字段，从 role_scope 或 read_scope 中填充。

        Args:
            item_dict: 包含 memory 数据的字典
            role_scope: 可选的 role scope
        """
        if role_scope is None:
            role_scope = self.get_read_scope()

        # 填充 user_id
        if "user_id" not in item_dict or not item_dict.get("user_id"):
            if role_scope.user_ids:
                item_dict["user_id"] = role_scope.user_ids[0]

        # 填充 agent_id
        if "agent_id" not in item_dict or not item_dict.get("agent_id"):
            if role_scope.agent_ids:
                item_dict["agent_id"] = role_scope.agent_ids[0]

    def _get_default_user_id(self) -> str:
        """获取默认的 user_id（当前 ctx 的 user_id）"""
        return self.ctx.user.user_id

    def _get_default_agent_id(self) -> str:
        """获取默认的 agent_id（当前 ctx 的 agent_id）"""
        return self.ctx.user.agent_id

    def _calculate_user_space(self, role_id: str) -> str:
        """
        根据 namespace policy 计算 user_space。

        isolate_user_scope_by_agent:
        - false: 返回 role_id
        - true: 返回 "role_id/agent/agent_id"
        """
        policy = self.ctx.namespace_policy
        if policy.isolate_user_scope_by_agent:
            # 需要额外 agent 维度
            agent_id = self._get_default_agent_id()
            return f"{role_id}/agent/{agent_id}"
        return role_id

    def _calculate_agent_space(self, role_id: str) -> str:
        """
        根据 namespace policy 计算 agent_space。

        isolate_agent_scope_by_user:
        - false: 返回 role_id
        - true: 返回 "role_id/user/user_id"
        """
        policy = self.ctx.namespace_policy
        if policy.isolate_agent_scope_by_user:
            # 需要额外 user 维度
            user_id = self._get_default_user_id()
            return f"{role_id}/user/{user_id}"
        return role_id

    def _calculate_target_for_role(
        self,
        role_id: str,
        role_type: str,
        memory_type: str,
    ) -> MemoryTarget:
        """为指定 role_id 计算写入目标"""
        policy = self.ctx.namespace_policy
        account_id = self.ctx.account_id

        if role_type == "user":
            user_space = self._calculate_user_space(role_id)
            agent_space = self.ctx.user.agent_id  # 默认 agent_id

            if policy.isolate_user_scope_by_agent:
                # URI 形如 viking://user/{user_id}/agent/{agent_id}/memories/{memory_type}
                base_uri = f"viking://user/{role_id}/agent/{self._get_default_agent_id()}"
                owner_user_id = role_id
                owner_agent_id = self._get_default_agent_id()
            else:
                # URI 形如 viking://user/{user_id}/memories/{memory_type}
                base_uri = f"viking://user/{role_id}"
                owner_user_id = role_id
                owner_agent_id = None

            return MemoryTarget(
                uri=f"{base_uri}/memories/{memory_type}",
                owner_user_id=owner_user_id,
                owner_agent_id=owner_agent_id,
                user_space=user_space,
                agent_space=agent_space,
            )

        else:  # role_type == "agent"
            agent_space = self._calculate_agent_space(role_id)
            logger.info(
                f"[MemoryIsolation] agent type: role_id={role_id}, isolate_agent_scope_by_user={policy.isolate_agent_scope_by_user}"
            )

            if policy.isolate_agent_scope_by_user:
                # 需要 user 维度，从对话参与者获取 user_id
                participant_user_ids = self.get_participant_user_ids()
                logger.info(f"[MemoryIsolation] participant_user_ids={participant_user_ids}")
                user_space = participant_user_ids[0] if participant_user_ids else None
                owner_user_id = user_space
                # URI 形如 viking://agent/{agent_id}/user/{user_id}/memories/{memory_type}
                base_uri = f"viking://agent/{role_id}/user/{user_space}"
            else:
                # 不需要 user 维度
                user_space = None
                owner_user_id = None
                # URI 形如 viking://agent/{agent_id}/memories/{memory_type}
                base_uri = f"viking://agent/{role_id}"

            owner_agent_id = role_id
            logger.info(f"[MemoryIsolation] agent target: user_space={user_space}, base_uri={base_uri}")

            return MemoryTarget(
                uri=f"{base_uri}/memories/{memory_type}",
                owner_agent_id=owner_agent_id,
                owner_user_id=owner_user_id,
                user_space=user_space,
                agent_space=agent_space,
            )

    def _get_default_target(self, role_type: str, memory_type: str) -> MemoryTarget:
        """获取当前 ctx 默认的写入目标"""
        if role_type == "user":
            return self._calculate_target_for_role(
                self.ctx.user.user_id, "user", memory_type
            )
        else:
            return self._calculate_target_for_role(
                self.ctx.user.agent_id, "agent", memory_type
            )

    def _extract_role_ids_from_messages_range(
        self, ranges: Optional[str]
    ) -> List[str]:
        """
        从 events 的 ranges 字段提取涉及的 role_id。

        解析 ranges 格式，提取范围内的所有 user 角色的消息参与者。
        """
        if not ranges or not self._extract_context:
            return []

        # 复用 ExtractContext.read_message_ranges() 解析 ranges
        from openviking.session.memory.memory_updater import ExtractContext

        if not isinstance(self._extract_context, ExtractContext):
            # 如果不是 ExtractContext 实例，尝试直接访问 messages
            messages = getattr(self._extract_context, "messages", None)
            if not messages:
                return []
        else:
            # 使用 ExtractContext 的方法解析 ranges
            msg_range = self._extract_context.read_message_ranges(ranges)
            messages = msg_range.elements

        # 从消息中提取 user 角色的 role_id
        user_ids: Set[str] = set()
        for msg in messages:
            if hasattr(msg, "role") and msg.role == "user" and hasattr(msg, "role_id") and msg.role_id:
                user_ids.add(msg.role_id)

        return list(user_ids)

    def _get_role_ids_from_operation(
        self, operation: Optional[Dict[str, Any]], role_type: str = "user"
    ) -> List[str]:
        """
        从 operation 中提取 role_ids。

        根据 role_type 决定提取策略：
        - user: 从 user_id 或 ranges 字段提取
        - agent: 从 agent_id 字段提取
        """
        if not operation:
            return []

        if role_type == "user":
            # 1. 如果 operation 返回了 user_id 字段（单个用户）
            if "user_id" in operation:
                user_id = operation.get("user_id")
                if user_id:
                    return [user_id]

            # 2. 如果有 ranges 字段 → 从 range 获取
            if "ranges" in operation:
                ranges = operation.get("ranges")
                return self._extract_role_ids_from_messages_range(ranges)
        else:
            # agent 类型: 从 agent_id 字段提取
            if "agent_id" in operation:
                agent_id = operation.get("agent_id")
                if agent_id:
                    return [agent_id]

        return []

    def calculate_memory_targets(
        self,
        role_id: Optional[str],
        role_type: str,
        memory_type: str,
        schema_directory: str,
        operation: Optional[Dict[str, Any]] = None,
    ) -> List[MemoryTarget]:
        """
        计算记忆的写入目标目录。

        Args:
            role_id: 记忆归属的 role_id（向后兼容，单个用户时使用）
            role_type: "user" 或 "agent"
            memory_type: 记忆类型（events, preferences, entities 等）
            schema_directory: schema 的 directory 模板，用于判断依赖
            operation: LLM 返回的 operation 字典，从中自动提取 user_id/user_ids/ranges

        Returns:
            MemoryTarget 列表，每个目标对应一个写入目录
        """
        policy = self.ctx.namespace_policy
        has_ranges = operation and "ranges" in operation if operation else False

        logger.info(
            f"[MemoryIsolation] calculate_memory_targets: role_id={role_id}, "
            f"role_type={role_type}, memory_type={memory_type}, directory={schema_directory}, "
            f"policy.isolate_user_scope_by_agent={policy.isolate_user_scope_by_agent}, "
            f"policy.isolate_agent_scope_by_user={policy.isolate_agent_scope_by_user}, "
            f"has_ranges={has_ranges}"
        )

        # 获取 read_scope
        read_scope = self.get_read_scope()

        # 根据新逻辑决定 target_role_ids
        target_role_ids: List[str] = []

        if role_type == "user":
            # 判断是否需要明确 user_id
            needs_user_id = self.needs_explicit_user_id(
                schema_directory,
                policy.isolate_agent_scope_by_user,
                has_ranges,
            )

            if not needs_user_id:
                # user_ids <= 1，不需要 LLM 输出
                target_role_ids = read_scope.user_ids[:1] if read_scope.user_ids else []
                logger.info(f"[MemoryIsolation] no explicit user_id needed, using read_scope.user_ids[:1]={target_role_ids}")
            else:
                # 需要从 operation 提取
                target_role_ids = self._get_role_ids_from_operation(operation, "user")
                if not target_role_ids and role_id:
                    target_role_ids = [role_id]
                if not target_role_ids:
                    target_role_ids = read_scope.user_ids
                logger.info(f"[MemoryIsolation] needs user_id, extracted target_role_ids={target_role_ids}")
        else:
            # agent 类型
            needs_agent_id = self.needs_explicit_agent_id(
                schema_directory,
                policy.isolate_user_scope_by_agent,
            )

            if not needs_agent_id:
                # agent_ids <= 1，不需要 LLM 输出
                target_role_ids = read_scope.agent_ids[:1] if read_scope.agent_ids else []
                logger.info(f"[MemoryIsolation] no explicit agent_id needed, using read_scope.agent_ids[:1]={target_role_ids}")
            else:
                # 需要从 operation 提取
                target_role_ids = self._get_role_ids_from_operation(operation, "agent")
                if not target_role_ids and role_id:
                    target_role_ids = [role_id]
                if not target_role_ids:
                    target_role_ids = read_scope.agent_ids
                logger.info(f"[MemoryIsolation] needs agent_id, extracted target_role_ids={target_role_ids}")

        # 校验所有 role_id 并生成 targets
        targets = []
        for uid in target_role_ids:
            # 校验 role_id
            if not self.validate_role_id(uid, role_type):
                valid_ids = self.get_valid_role_ids(role_type)
                logger.warning(
                    f"[MemoryIsolation] validate_role_id failed: uid={uid}, valid_ids={valid_ids}"
                )
                continue
            targets.append(self._calculate_target_for_role(uid, role_type, memory_type))

        if not targets:
            # fallback 到默认目标
            logger.warning(f"[MemoryIsolation] no targets, using fallback")
            targets = [self._get_default_target(role_type, memory_type)]

        return targets