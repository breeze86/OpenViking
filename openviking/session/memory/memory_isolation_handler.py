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
class Participant:
    """参与者信息"""

    role_id: str  # user 或 agent 的 ID
    role_type: str  # "user" 或 "agent"
    account_id: str


@dataclass
class MemoryTarget:
    """记忆写入目标"""

    uri: str  # 完整的 canonical URI
    owner_user_id: Optional[str]
    owner_agent_id: Optional[str]
    user_space: str  # 用于 URI 生成
    agent_space: str  # 用于 URI 生成


class MemoryIsolationHandler:
    """Memory isolation handler."""

    def __init__(self, ctx: RequestContext, extract_context: Any):
        self.ctx = ctx
        self._extract_context = extract_context
        self._participants: List[Participant] = []
        self._participants_loaded = False

    def load_participants(self) -> None:
        """
        Load participants from extract_context.messages.

        Iterates through all messages and extracts participants:
        - role="user" -> role_id is user_id
        - role="assistant" -> role_id is agent_id
        """
        messages = self._extract_context.messages if self._extract_context else []
        seen_users: Set[str] = set()
        seen_agents: Set[str] = set()

        for msg in messages:
            role = msg.role
            role_id = msg.role_id

            if not role_id:
                continue

            if role == "user":
                if role_id not in seen_users:
                    seen_users.add(role_id)
                    self._participants.append(
                        Participant(
                            role_id=role_id,
                            role_type="user",
                            account_id=self.ctx.account_id,
                        )
                    )
            elif role == "assistant":
                if role_id not in seen_agents:
                    seen_agents.add(role_id)
                    self._participants.append(
                        Participant(
                            role_id=role_id,
                            role_type="agent",
                            account_id=self.ctx.account_id,
                        )
                    )

        # Fallback to ctx defaults if no participants found
        if not self._participants:
            logger.warning(
                f"No participants extracted from messages, using ctx defaults: "
                f"user_id={self.ctx.user.user_id}, agent_id={self.ctx.user.agent_id}"
            )
            self._participants.append(
                Participant(
                    role_id=self.ctx.user.user_id,
                    role_type="user",
                    account_id=self.ctx.account_id,
                )
            )
            self._participants.append(
                Participant(
                    role_id=self.ctx.user.agent_id,
                    role_type="agent",
                    account_id=self.ctx.account_id,
                )
            )

        self._participants_loaded = True
        logger.info(
            f"Loaded {len(self._participants)} participants: "
            f"users={[p.role_id for p in self._participants if p.role_type == 'user']}, "
            f"agents={[p.role_id for p in self._participants if p.role_type == 'agent']}"
        )
        logger.info(
            f"Loaded {len(self._participants)} participants: "
            f"users={[p.role_id for p in self._participants if p.role_type == 'user']}, "
            f"agents={[p.role_id for p in self._participants if p.role_type == 'agent']}"
        )

    def get_participant_user_ids(self) -> List[str]:
        """获取所有参与者的 user_id 列表"""
        return [p.role_id for p in self._participants if p.role_type == "user"]

    def get_participant_agent_ids(self) -> List[str]:
        """获取所有参与者的 agent_id 列表"""
        return [p.role_id for p in self._participants if p.role_type == "agent"]

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
            user_space = self.ctx.user.user_id  # 默认 user_id

            if policy.isolate_agent_scope_by_user:
                # URI 形如 viking://agent/{agent_id}/user/{user_id}/memories/{memory_type}
                base_uri = f"viking://agent/{role_id}/user/{self._get_default_user_id()}"
                owner_agent_id = role_id
                owner_user_id = self._get_default_user_id()
            else:
                # URI 形如 viking://agent/{agent_id}/memories/{memory_type}
                base_uri = f"viking://agent/{role_id}"
                owner_agent_id = role_id
                owner_user_id = None

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

    def _extract_role_ids_from_events_range(
        self, events_range: Optional[Dict[str, Any]]
    ) -> List[str]:
        """
        从 events 的 ranges 字段提取涉及的 role_id。

        简化实现：如果有 ranges 信息，提取范围内的所有消息的参与者。
        如果无法解析，返回空列表（将使用所有参与者）。
        """
        if not events_range:
            return []

        # ranges 格式: "0-3,40-45" 或 "[0, 1, 2, 3]"
        # 这里简化处理：假设调用方已经传入需要归属的 user_id 列表
        # 实际实现可以从 extract_context.read_message_ranges() 获取消息，再提取 role_id
        return []

    def _get_user_ids_from_operation(
        self, operation: Optional[Dict[str, Any]]
    ) -> List[str]:
        """
        从 operation 中提取 user_ids。

        根据字段名自动推断：
        - user_id: 单个用户
        - ranges: 从 message range 获取
        - 都没有: 返回空列表（调用方会使用所有参与者）
        """
        if not operation:
            return []

        # 1. 如果 operation 返回了 user_id 字段（单个用户）
        if "user_id" in operation:
            user_id = operation.get("user_id")
            if user_id:
                return [user_id]

        # 2. 如果有 ranges 字段 → 从 range 获取
        if "ranges" in operation:
            ranges = operation.get("ranges")
            return self._extract_role_ids_from_events_range(ranges)

        return []

    def calculate_memory_targets(
        self,
        role_id: Optional[str],
        role_type: str,
        memory_type: str,
        operation: Optional[Dict[str, Any]] = None,
    ) -> List[MemoryTarget]:
        """
        计算记忆的写入目标目录。

        Args:
            role_id: 记忆归属的 role_id（向后兼容，单个用户时使用）
            role_type: "user" 或 "agent"
            memory_type: 记忆类型（events, preferences, entities 等）
            operation: LLM 返回的 operation 字典，从中自动提取 user_id/user_ids/ranges

        Returns:
            MemoryTarget 列表，每个目标对应一个写入目录
        """
        # 从 operation 中提取 user_ids
        target_role_ids = self._get_user_ids_from_operation(operation)

        # 如果无法从 operation 确定，使用 role_id 参数（向后兼容）
        if not target_role_ids and role_id:
            target_role_ids = [role_id]

        # 如果仍然无法确定，使用所有参与者
        if not target_role_ids:
            if role_type == "user":
                target_role_ids = self.get_participant_user_ids()
            else:
                target_role_ids = self.get_participant_agent_ids()

        # 校验所有 role_id 并生成 targets
        targets = []
        for uid in target_role_ids:
            # 校验 role_id
            if not self.validate_role_id(uid, role_type):
                valid_ids = self.get_valid_role_ids(role_type)
                raise ValueError(
                    f"role_id '{uid}' is not in session participants. "
                    f"Valid {role_type} participants: {valid_ids}"
                )
            targets.append(self._calculate_target_for_role(uid, role_type, memory_type))

        if not targets:
            # fallback 到默认目标
            targets = [self._get_default_target(role_type, memory_type)]

        return targets