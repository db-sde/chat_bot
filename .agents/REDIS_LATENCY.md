# Redis Latency & Deployment Topology Recommendation

This document analyzes the current Redis implementation in the DegreeBaba Chatbot codebase and outlines the recommended deployment topology modifications to achieve high availability, failover resilience, and session consistency.

---

## 1. Current Redis Architecture & Connection Parameters

### Connection Configuration
The chatbot utilizes a Redis-backed session store (`chatbot/session/store.py`) configured with the following defaults via `chatbot/config.py`:
- **Redis Connection String (`REDIS_URL`)**: Configured via environment variables.
- **Key Prefix (`redis_key_prefix`)**: `degreebaba:session:`
- **Timeout Settings (`redis_timeout_seconds`)**: `1.0` seconds (default). This applies to both:
  - `socket_connect_timeout`: Timeout for establishing TCP connection to the Redis server.
  - `socket_timeout`: Timeout for read/write operations on the established socket.
- **Session TTL (`session_ttl_seconds`)**: 30 minutes (`1800` seconds), with a sliding expiration updated on every read.

### Current Outage/Degradation Behavior
- When a Redis read/write or TTL refresh operation fails, the system logs a warning and marks `self._redis_failed = True`.
- **Permanent Local Fallback**: Once `self._redis_failed` is set to `True`, the session store **permanently bypasses Redis** for the remainder of the application lifecycle and uses local process memory (`self._memory`).
- **Warm Mirroring**: The store keeps an in-memory duplicate of read/written states to prevent session loss at the moment of the Redis outage.

---

## 2. Latency & RTT Findings

- **Socket Timeout (1.0s)**: While a 1.0-second timeout acts as a fallback gate, in high-throughput environments, letting a request block for up to 1000ms due to RTT spike or TCP handshake delays will queue upstream threads and degrade user experience. Under ordinary cloud deployments (same region/VPC), Redis RTT should be sub-millisecond to low single-digit milliseconds (<5ms).
- **Network Glitches**: Transient packet losses or packet retransmissions (which take up to 200ms–500ms on TCP retransmission timers) can easily exceed sub-millisecond thresholds but should not trigger a permanent downgrade of the entire node's state store.

---

## 3. Recommended Deployment Topology Changes

For production environments with load-balanced application instances, the current strategy presents several high-availability (HA) and consistency challenges. We recommend the following changes:

### A. Eliminate Permanently Sticky Memory Fallbacks
* **The Problem**: In a load-balanced topology (e.g., multiple ECS tasks, Kubernetes pods, or VM instances behind an ALB), if Node A suffers a transient connection glitch to Redis, it permanently falls back to local memory. Node B remains connected to Redis. Subsequent requests for the same session ID will receive divergent state depending on which node they land on, causing session fragmentation.
* **The Solution**: Implement a **Circuit Breaker Pattern** instead of permanent sticky degradation.
  - When Redis fails, open the circuit and route requests to local memory.
  - Configure a cooldown period (e.g., 30 seconds).
  - After the cooldown, attempt a single "half-open" check (e.g. a ping) to see if Redis has recovered. If successful, close the circuit and resume using Redis.

### B. Configure TCP Keepalives
* **The Problem**: Firewalls, cloud NAT gateways, and load balancers frequently drop idle TCP connections without notifying the clients. When the application tries to reuse an idle connection, it blocks until the 1.0s timeout expires.
* **The Solution**: Explicitly pass keepalive configurations to the Redis client initialization:
  ```python
  self._redis = Redis.from_url(
      effective_url,
      decode_responses=True,
      socket_connect_timeout=self.timeout_seconds,
      socket_timeout=self.timeout_seconds,
      socket_keepalive=True,
      socket_keepalive_options={
          socket.TCP_KEEPIDLE: 60,
          socket.TCP_KEEPINTVL: 10,
          socket.TCP_KEEPCNT: 3
      }
  )
  ```
  This ensures the kernel regularly pings the Redis socket, keeping it active and detecting dead sockets immediately.

### C. Implement Tenacity Retries for Transient Errors
* **The Problem**: A single dropped packet can trigger the fallback mechanism immediately.
* **The Solution**: Wrap Redis operations with a lightweight retry mechanism (e.g., using `tenacity`) for connection resets or timeouts. Use 2 quick retries with a small jittered backoff (e.g., 50ms) before giving up and failing over:
  ```python
  from tenacity import retry, stop_after_attempt, wait_random_exponential, retry_if_exception_type
  
  @retry(
      stop=stop_after_attempt(3),
      wait=wait_random_exponential(min=0.01, max=0.05),
      retry=retry_if_exception_type(redis.exceptions.ConnectionError),
      reraise=True
  )
  async def _redis_operation_with_retry(self):
      ...
  ```

### D. Use High Availability Redis Topologies
* For high-traffic production, replace a single Redis node with:
  1. **Redis Sentinel**: Provides automatic master/replica failover. The client handles failover orchestration.
  2. **AWS ElastiCache for Redis (Cluster Mode Enabled)**: Managed replication and partitioning, allowing smooth scaling and sub-second failover.
  3. **Read/Write Splitting**: Route writes to the master node and session reads to read replicas to reduce resource contention.
