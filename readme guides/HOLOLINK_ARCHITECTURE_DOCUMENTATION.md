# HoloLink Architecture Documentation

**Generated:** January 26, 2026  
**Scope:** Complete API analysis of hololink/core, hololink/common, hololink/operators, and hololink/sensors

---

## Table of Contents

1. [Core Module](#core-module)
2. [Common Module](#common-module)
3. [Operators Module](#operators-module)
4. [Sensors Module](#sensors-module)
5. [Usage Patterns & Integration](#usage-patterns--integration)
6. [Type Definitions & Constants](#type-definitions--constants)

---

## Core Module

### Overview
The core module contains the fundamental abstractions for HSB (Holoscan Sensor Bridge) device communication, data channel management, and peripheral interfacing.

---

### 1. **Hololink Class**

**Purpose:** Primary interface for communicating with HSB devices over Ethernet. Manages control plane communications, I2C/SPI peripherals, GPIO, and synchronization.

#### Constructor
```cpp
explicit Hololink(
    const std::string& peer_ip, 
    uint32_t control_port, 
    const std::string& serial_number, 
    bool sequence_number_checking, 
    bool skip_sequence_initialization = false, 
    bool ptp_enable = true, 
    bool vsync_enable = true, 
    bool block_enable = true
);
```

#### Factory Methods
- **`static std::shared_ptr<Hololink> from_enumeration_metadata(const Metadata& metadata)`**
  - Creates Hololink instance from device enumeration data
  - Returns: Configured Hololink instance

- **`static void reset_framework()`**
  - Resets the Hololink framework globally

- **`static bool enumerated(const Metadata& metadata)`**
  - Checks if metadata corresponds to an enumerated device
  - Returns: true if device is valid

#### Lifecycle Methods
- **`void start()`** - Initialize local resources (control plane socket, etc.)
- **`void stop()`** - Stop device communication
- **`void reset()`** - Reset the device

#### Register Read/Write Methods

**Single Register Operations:**
```cpp
// Write operations
bool write_uint32(uint32_t address, uint32_t value);
bool write_uint32(uint32_t address, uint32_t value, const std::shared_ptr<Timeout>& timeout, bool retry = true);
bool write_uint32(uint32_t address, uint32_t value, const std::shared_ptr<Timeout>& timeout, 
                  bool retry, bool sequence_check);

// Read operations
uint32_t read_uint32(uint32_t address);
uint32_t read_uint32(uint32_t address, const std::shared_ptr<Timeout>& timeout);
uint32_t read_uint32(uint32_t address, const std::shared_ptr<Timeout>& timeout, bool sequence_check);

// Block read operations
std::tuple<bool, std::vector<uint32_t>> read_uint32(uint32_t address, uint32_t count, 
                                                     const std::shared_ptr<Timeout>& timeout, 
                                                     bool sequence_check = true);
```

**WriteData Class for Batched Writes:**
```cpp
class WriteData {
    void queue_write_uint32(uint32_t address, uint32_t value);
    size_t size();
    std::string stringify();
};

bool write_uint32(WriteData& data, const std::shared_ptr<Timeout> timeout = nullptr, bool retry = true);
```

#### Version & Status Methods
```cpp
uint32_t get_hsb_ip_version(const std::shared_ptr<Timeout>& timeout = nullptr, bool sequence_check = true);
uint32_t get_fpga_date();
```

#### Clock Configuration
```cpp
void setup_clock(const std::vector<std::vector<uint8_t>>& clock_profile);
```

#### Named Lock Class (Multi-Process Synchronization)
```cpp
class NamedLock {
    NamedLock(Hololink& hololink, std::string name);
    void lock();
    void unlock();
};
```

#### I2C Interface

**I2c Abstract Class:**
```cpp
class I2c {
    virtual bool set_i2c_clock() = 0;
    
    virtual std::vector<uint8_t> i2c_transaction(
        uint32_t peripheral_i2c_address,
        const std::vector<uint8_t>& write_bytes, 
        uint32_t read_byte_count,
        const std::shared_ptr<Timeout>& timeout = nullptr,
        bool ignore_nak = false
    ) = 0;
    
    virtual std::tuple<std::vector<unsigned>, std::vector<unsigned>, unsigned> 
        encode_i2c_request(Sequencer& sequencer,
                          uint32_t peripheral_i2c_address,
                          const std::vector<uint8_t>& write_bytes, 
                          uint32_t read_byte_count) = 0;
};

std::shared_ptr<I2c> get_i2c(uint32_t i2c_bus, uint32_t i2c_address = I2C_CTRL);
NamedLock& i2c_lock();
```

#### SPI Interface

**Spi Abstract Class:**
```cpp
class Spi {
    virtual std::vector<uint8_t> spi_transaction(
        const std::vector<uint8_t>& write_command_bytes,
        const std::vector<uint8_t>& write_data_bytes, 
        uint32_t read_byte_count,
        const std::shared_ptr<Timeout>& timeout = nullptr
    ) = 0;
};

std::shared_ptr<Spi> get_spi(
    uint32_t bus_number, 
    uint32_t chip_select,
    uint32_t clock_divisor = 0x0F, 
    uint32_t cpol = 1, 
    uint32_t cpha = 1, 
    uint32_t width = 1, 
    uint32_t spi_address = SPI_CTRL
);

NamedLock& spi_lock();
```

#### GPIO Interface

**GPIO Class:**
```cpp
class GPIO {
    explicit GPIO(Hololink& hololink, uint32_t gpio_pin_number);
    
    // Direction constants
    static constexpr uint32_t IN = 1;
    static constexpr uint32_t OUT = 0;
    
    // Value constants
    static constexpr uint32_t LOW = 0;
    static constexpr uint32_t HIGH = 1;
    
    // GPIO pin range (0-255)
    static constexpr uint32_t GPIO_PIN_RANGE = 0x100;
    
    void set_direction(uint32_t pin, uint32_t direction);
    uint32_t get_direction(uint32_t pin);
    void set_value(uint32_t pin, uint32_t value);
    uint32_t get_value(uint32_t pin);
    uint32_t get_supported_pin_num();
};

std::shared_ptr<GPIO> get_gpio(Metadata& metadata);
```

#### Sequencer Class (Command Sequencing)

**Purpose:** Build sequences of I2C/SPI operations synchronized with frame-end events

```cpp
class Sequencer {
    enum Op { POLL = 0, WR = 1, RD = 2 };
    
    explicit Sequencer(unsigned limit = 0x200);
    
    virtual void enable() = 0;
    
    // Sequence operations
    unsigned write_uint32(uint32_t address, uint32_t data);
    unsigned read_uint32(uint32_t address, uint32_t initial_value = 0xFFFFFFFF);
    unsigned poll(uint32_t address, uint32_t mask, uint32_t match);
    
    uint32_t location();
};

std::shared_ptr<Hololink::Sequencer> software_sequencer();
```

#### Event Handling

**Event Types:**
```cpp
enum Event {
    I2C_BUSY = 0,
    SW_EVENT = 2,
    SIF_0_FRAME_END = 16,
    SIF_1_FRAME_END = 17
};

void configure_apb_event(Event event, uint32_t handler = 0, bool rising_edge = true);
void clear_apb_event(Event event);
void configure_apb_event(WriteData&, Event event, uint32_t handler = 0, bool rising_edge = true);
void clear_apb_event(WriteData&, Event event);
```

#### Synchronization Classes

**Synchronizable Base Class:**
```cpp
class Synchronizable {
    Synchronizable();
    virtual ~Synchronizable() = default;
};
```

**Synchronizer Abstract Class:**
```cpp
class Synchronizer {
    static std::shared_ptr<Synchronizer> null_synchronizer();
    
    void attach(std::shared_ptr<Synchronizable> peer);
    void detach(std::shared_ptr<Synchronizable> peer);
    
    virtual void setup() = 0;
    virtual void shutdown() = 0;
    virtual bool is_enabled() = 0;
};
```

**PtpSynchronizer Class:**
```cpp
class PtpSynchronizer : public Synchronizer {
    PtpSynchronizer(Hololink&);
    void set_frequency(unsigned frequency);
    void setup() override;
    void shutdown() override;
    bool is_enabled() override;
};

bool ptp_synchronize(const std::shared_ptr<Timeout>& timeout);
bool ptp_synchronize(); // 20-second default timeout
std::shared_ptr<Synchronizer> ptp_pps_output(unsigned frequency = 0);
```

#### Reset Controller Interface

```cpp
class ResetController {
    virtual ~ResetController();
    virtual void reset() = 0;
};

void on_reset(std::shared_ptr<ResetController> reset_controller);
```

#### Frame Metadata Deserialization

```cpp
struct FrameMetadata {
    uint32_t flags;
    uint32_t psn;
    uint32_t crc;
    uint16_t frame_number;
    uint32_t timestamp_ns;
    uint64_t timestamp_s;
    uint64_t bytes_written;
    uint32_t metadata_ns;
    uint64_t metadata_s;
};

static FrameMetadata deserialize_metadata(const uint8_t* metadata_buffer, 
                                          unsigned metadata_buffer_size);
```

#### Exception Classes
- **`TimeoutError`** - Thrown when operation times out
- **`UnsupportedVersion`** - Thrown when FPGA version is unsupported

---

### 2. **DataChannel Class**

**Purpose:** Abstracts the data plane configuration for RoCe (RDMA over Converged Ethernet) and COE (AVTP/1722B) packet transmission.

#### Constructor
```cpp
DataChannel(const Metadata& metadata,
            const std::function<std::shared_ptr<Hololink>(const Metadata& metadata)>& create_hololink
            = Hololink::from_enumeration_metadata);
```

#### Static Methods
```cpp
static bool enumerated(const Metadata& metadata);
static void use_multicast(Metadata& metadata, std::string address, uint16_t port);
static void use_broadcast(Metadata& metadata, uint16_t port);
static void use_sensor(Metadata& metadata, int64_t sensor_number);
static void use_data_plane_configuration(Metadata& metadata, int64_t data_plane);
```

#### Instance Methods
```cpp
std::shared_ptr<Hololink> hololink() const;
const std::string& peer_ip() const;

void authenticate(uint32_t qp_number, uint32_t rkey);

// RoCe configuration
void configure_roce(uint64_t frame_memory, size_t frame_size, size_t page_size, 
                   unsigned pages, uint32_t local_data_port);

// COE/1722B configuration
void configure_coe(uint8_t channel, size_t frame_size, uint32_t pixel_width, 
                  bool vlan_enabled = false);

void unconfigure();
void configure_socket(int socket_fd);

// Packetizer control
void disable_packetizer();
void enable_packetizer_10(); // 10-bit data
void enable_packetizer_12(); // 12-bit data

std::shared_ptr<Hololink::Sequencer> frame_end_sequencer();

Metadata& enumeration_metadata();
```

---

### 3. **Enumerator Class**

**Purpose:** Handles device discovery via BOOTP protocol and manages enumeration strategies.

#### Constructor
```cpp
explicit Enumerator(
    const std::string& local_interface = "",
    uint32_t bootp_request_port = 12267u,
    uint32_t bootp_reply_port = 12268u
);
```

#### Static Enumeration Methods
```cpp
static void enumerated(
    const std::function<bool(Metadata&)>& callback,
    const std::shared_ptr<Timeout>& timeout = nullptr
);

static Metadata find_channel(
    const std::string& channel_ip,
    const std::shared_ptr<Timeout>& timeout = std::make_shared<Timeout>(20.f)
);
```

#### Packet-Level Access
```cpp
void enumeration_packets(
    const std::function<bool(Enumerator&, const std::vector<uint8_t>&, Metadata&)>& callback,
    const std::shared_ptr<Timeout>& timeout = nullptr
);

void send_bootp_reply(const std::string& peer_address, 
                     const std::string& reply_packet, 
                     Metadata& metadata);
```

#### Enumeration Strategy Management
```cpp
class EnumerationStrategy {
    virtual ~EnumerationStrategy();
    virtual void update_metadata(Metadata& metadata, hololink::core::Deserializer& deserializer) = 0;
    virtual void use_sensor(Metadata& metadata, int64_t sensor_number) = 0;
    virtual void use_data_plane_configuration(Metadata& metadata, int64_t data_plane) = 0;
};

static std::shared_ptr<EnumerationStrategy> set_uuid_strategy(
    std::string uuid, 
    std::shared_ptr<EnumerationStrategy> strategy
);
static EnumerationStrategy& get_uuid_strategy(std::string uuid);
```

#### BasicEnumerationStrategy
```cpp
class BasicEnumerationStrategy : public EnumerationStrategy {
    BasicEnumerationStrategy(const Metadata& additional_metadata, 
                            unsigned total_sensors = 2, 
                            unsigned total_dataplanes = 2, 
                            unsigned sifs_per_sensor = 2);
    
    void ptp_enable(bool enable);
    void vsync_enable(bool enable);
    void block_enable(bool enable);
    
    void update_metadata(Metadata& metadata, hololink::core::Deserializer& deserializer) override;
    void use_sensor(Metadata& metadata, int64_t sensor_number) override;
    void use_data_plane_configuration(Metadata& metadata, int64_t data_plane) override;
};
```

#### Device UUIDs
```cpp
const std::string HOLOLINK_LITE_UUID = "889b7ce3-65a5-4247-8b05-4ff1904c3359";
const std::string HOLOLINK_NANO_UUID = "d0f015e0-93b6-4473-b7d1-7dbd01cbeab5";
const std::string HOLOLINK_100G_UUID = "7a377bf7-76cb-4756-a4c5-7dddaed8354b";
const std::string MICROCHIP_POLARFIRE_UUID = "ed6a9292-debf-40ac-b603-a24e025309c1";
const std::string LEOPARD_EAGLE_UUID = "f1627640-b4dc-48af-a360-c55b09b3d230";
```

---

### 4. **Timeout Class**

**Purpose:** Manages timeout and retry logic for bus transactions.

#### Constructor
```cpp
explicit Timeout(float timeout_s, float retry_s = 0.f);
explicit Timeout(const Timeout& source);
```

#### Static Factory Methods
```cpp
static std::shared_ptr<Timeout> default_timeout(
    const std::shared_ptr<Timeout>& timeout = nullptr
);

static std::shared_ptr<Timeout> i2c_timeout(
    const std::shared_ptr<Timeout>& timeout = nullptr
);

static std::shared_ptr<Timeout> spi_timeout(
    const std::shared_ptr<Timeout>& timeout = nullptr
);
```

#### Query Methods
```cpp
static double now_s();           // Monotonic clock in seconds
static int64_t now_ns();         // Monotonic clock in nanoseconds
bool expired() const;            // Check if timeout has expired
float trigger_s() const;         // Time in seconds until timeout (can be negative)
bool retry();                    // Check if should retry
```

---

### 5. **Metadata Class**

**Purpose:** Container for device enumeration and configuration metadata with type-safe access.

```cpp
class Metadata : public std::map<std::string, std::variant<int64_t, std::string, std::vector<uint8_t>>> {
    
    // Type-safe get with optional return
    template <typename T>
    std::optional<const T> get(const std::string& name) const;
    
    // Update with values from another metadata object
    void update(const Metadata& other);
};
```

---

### 6. **Networking Module (core/networking.hpp)**

**Purpose:** Network discovery and MAC address resolution utilities.

#### Constants
```cpp
constexpr uint32_t UDP_PACKET_SIZE = 10240;  // Supports 9k jumbo packets
constexpr uint32_t PAGE_SIZE = 128;          // I/O alignment size
```

#### Type Definitions
```cpp
using MacAddress = std::array<uint8_t, 6>;
using UniqueFileDescriptor = std::unique_ptr<Nullable<int>, Nullable<int>::Deleter<int, &close>>;
```

#### Network Utility Functions
```cpp
size_t round_up(size_t value, size_t alignment);

std::tuple<std::string, std::string, MacAddress> local_ip_and_mac(
    const std::string& destination_ip, 
    uint32_t port = 1
);

std::tuple<std::string, std::string, MacAddress> local_ip_and_mac_from_socket(int socket_fd);

MacAddress local_mac(const std::string& interface);
```

---

### 7. **Deserializer & Serializer Classes**

**Purpose:** Low-level binary data marshaling with endianness support.

#### Deserializer Class
```cpp
class Deserializer {
    Deserializer(const uint8_t* buffer, size_t size);
    
    // LE (little-endian) reads
    bool next_uint32_le(uint32_t& result);
    bool next_uint16_le(uint16_t& result);
    bool next_uint8(uint8_t& result);
    
    // BE (big-endian) reads
    bool next_uint32_be(uint32_t& result);
    bool next_uint16_be(uint16_t& result);
    bool next_uint24_be(uint32_t& result);
    bool next_uint48_be(uint64_t& result);
    bool next_uint64_be(uint64_t& result);
};
```

#### Serializer Class
```cpp
class Serializer {
    Serializer(uint8_t* buffer, size_t size);
    
    unsigned length();
    
    // LE (little-endian) writes
    bool append_uint32_le(uint32_t value);
    bool append_uint16_le(uint16_t value);
    bool append_uint8(uint8_t value);
    
    // BE (big-endian) writes
    bool append_uint32_be(uint32_t value);
    bool append_uint16_be(uint16_t value);
    bool append_uint64_be(uint64_t value);
    
    // Buffer operations
    bool append_buffer(uint8_t* b, unsigned length);
};
```

---

### 8. **CSI (Camera Serial Interface) Modules**

#### CSI Format Definitions (csi_formats.hpp)
```cpp
enum class PixelFormat {
    RAW_8 = 0,   // 1 byte per pixel
    RAW_10 = 1,  // 10 bits per pixel (5 bytes = 4 pixels)
    RAW_12 = 2   // 12 bits per pixel (3 bytes = 2 pixels)
};

enum class BayerFormat {
    BGGR = 0,    // Bayer filter pattern
    RGGB = 1,
    GBRG = 2,
    GRBG = 3
};
```

#### CSI Controller Interface (csi_controller.hpp)
```cpp
class CsiConverter {
    CsiConverter() = default;
    
    virtual void configure(
        uint32_t start_byte, 
        uint32_t received_bytes_per_line, 
        uint32_t pixel_width, 
        uint32_t pixel_height, 
        PixelFormat pixel_format, 
        uint32_t trailing_bytes = 0
    ) = 0;
    
    virtual uint32_t receiver_start_byte() = 0;
    virtual uint32_t received_line_bytes(uint32_t line_bytes) = 0;
    virtual uint32_t transmitted_line_bytes(PixelFormat pixel_format, uint32_t pixel_width) = 0;
};
```

---

### 9. **JESD Configuration (jesd.hpp)**

**Purpose:** JESD204 serial link configuration for high-speed data interfaces.

#### JESDConfig Interface
```cpp
class JESDConfig {
    virtual ~JESDConfig();
    virtual void power_on() = 0;
    virtual void setup_clocks() = 0;
    virtual void configure() = 0;
    virtual void run() = 0;
};
```

#### SpiDaemonThread Class
```cpp
class SpiDaemonThread {
    explicit SpiDaemonThread(Hololink& hololink, JESDConfig& jesd_config);
    void run();   // Starts thread, blocks until connected
    void stop();  // Stops thread, blocks until complete
};
```

#### AD9986 Configuration
```cpp
class AD9986Config : public JESDConfig {
    explicit AD9986Config(Hololink& hololink);
    
    void host_pause_mapping(uint32_t mask);
    void apply();
    
    void power_on() override;
    void setup_clocks() override;
    void configure() override;
    void run() override;
};
```

---

### 10. **ARP Wrapper (arp_wrapper.hpp)**

**Purpose:** ARP protocol support for network configuration.

```cpp
class ArpWrapper {
    static int arp_set(int socket_fd, char const* eth_device, 
                       char const* ip, const char* mac_id);
};
```

---

## Common Module

### Overview
The common module provides utility classes and helpers for command-line argument parsing, CUDA integration, and GUI rendering.

---

### 1. **Holoargs - Command-Line Argument Parsing**

**Purpose:** Argument parsing inspired by Boost.Program_options.

#### Exception Classes
```cpp
class RequiredOption : public std::runtime_error {
    using std::runtime_error::runtime_error;
};
```

#### ValueSemantic Base Class
```cpp
class ValueSemantic : public std::enable_shared_from_this<ValueSemantic> {
    using Pointer = std::shared_ptr<ValueSemantic>;
    
    virtual bool is_required() const = 0;
    virtual std::string name() const = 0;
    virtual bool apply_default(std::any& value) const = 0;
    virtual void parse(std::any& value_store, const std::string& token) const = 0;
    virtual const std::type_info& value_type() const = 0;
};
```

#### TypedValue Template Class
```cpp
template <typename T>
class TypedValue : public ValueSemantic {
    using Pointer = std::shared_ptr<TypedValue<T>>;
    
    Pointer required();
    Pointer value_name(const std::string& name);
    Pointer default_value(const T& default_value);
    
    bool is_required() const override;
    std::string name() const override;
    bool apply_default(std::any& value) const override;
    void parse(std::any& value_store, const std::string& token) const override;
    const std::type_info& value_type() const override;
};

// Factory function
template <typename T>
typename TypedValue<T>::Pointer value();

TypedValue<bool>::Pointer bool_switch();
```

#### OptionDescription Classes
```cpp
class OptionDescription {
    OptionDescription(const std::string& name, int key, 
                     const std::string& doc, 
                     std::shared_ptr<const ValueSemantic> value_semantic = nullptr);
};

class OptionsDescriptionEasyInit {
    OptionsDescriptionEasyInit(OptionsDescription& options_description);
    OptionsDescriptionEasyInit& operator()(const std::string& name, 
                                           const std::string& doc);
    OptionsDescriptionEasyInit& operator()(const std::string& name, 
                                           std::shared_ptr<const ValueSemantic> value_semantic, 
                                           const std::string& doc);
};

class OptionsDescription {
    // ... full interface
};

class Parser {
    // ... full interface
};
```

---

### 2. **CUDA Helper Utilities**

**Purpose:** CUDA driver API error handling and kernel compilation/launching.

#### CUDA Error Checking Macro
```cpp
#define CudaCheck(FUNC) \
    { \
        const CUresult result = FUNC; \
        if (result != CUDA_SUCCESS) { \
            // Error handling and throwing runtime_error \
        } \
    }
```

#### CudaFunctionLauncher Class
```cpp
class CudaFunctionLauncher {
    CudaFunctionLauncher(const char* source, 
                        const std::vector<std::string>& functions, 
                        const std::vector<std::string>& options = {});
    ~CudaFunctionLauncher();
    
    // Launch with grid size
    template <class... TYPES>
    void launch(const std::string& name, const dim3& grid, 
               CUstream stream, TYPES... args) const;
    
    // Launch with grid and block size
    template <class... TYPES>
    void launch(const std::string& name, const dim3& grid, 
               const dim3& block, CUstream stream, TYPES... args) const;
};
```

---

### 3. **ImGui Renderer**

**Purpose:** Dedicated Dear ImGui rendering outside Holoscan operators with independent rendering thread.

#### ImGuiRenderer Class
```cpp
class ImGuiRenderer {
    using DrawFunction = std::function<void()>;
    using DrawFunctions = std::list<std::pair<std::string, DrawFunction>>;
    using Handle = DrawFunctions::reverse_iterator;
    
    ImGuiRenderer();
    ~ImGuiRenderer();
    
    Handle add_draw_function(const std::string& name, DrawFunction draw_func);
    void remove_draw_function(Handle);
    bool is_running() const;
};
```

#### CutCopyPaste Helper
```cpp
class CutCopyPaste {
    CutCopyPaste(std::string& str);
    CutCopyPaste(CutCopyPaste&) = delete;
    CutCopyPaste& operator=(CutCopyPaste&) = delete;
    
    void reset();
    void operator()(float width = 0);
    
    static int InputTextCallback(ImGuiInputTextCallbackData* data);
    static int InputTextCallback(CutCopyPaste* self, ImGuiInputTextCallbackData* data);
};
```

---

## Operators Module

### Overview
The operators module contains Holoscan operators for data reception, image processing, CSI capture, and ISP handling. These operators integrate with the Holoscan framework for dataflow processing.

---

### 1. **BaseReceiverOp Class**

**Purpose:** Abstract base operator for all data reception operators using RoCe or UDP.

#### Class Definition
```cpp
class BaseReceiverOp : public holoscan::Operator {
    HOLOSCAN_OPERATOR_FORWARD_ARGS(BaseReceiverOp);
    
    virtual ~BaseReceiverOp() = default;
    
    void setup(holoscan::OperatorSpec& spec) override;
    void start() override;
    void stop() override;
    void compute(holoscan::InputContext&, holoscan::OutputContext& op_output,
                holoscan::ExecutionContext&) override;
    
    // Protected members
    holoscan::Parameter<DataChannel*> hololink_channel_;
    holoscan::Parameter<std::function<void()>> device_start_;
    holoscan::Parameter<std::function<void()>> device_stop_;
    holoscan::Parameter<CUcontext> frame_context_;
    holoscan::Parameter<size_t> frame_size_;
    holoscan::Parameter<bool> trim_;
    std::shared_ptr<holoscan::AsynchronousCondition> frame_ready_condition_;
    uint64_t frame_count_;
    core::UniqueFileDescriptor data_socket_;
};
```

#### Protected Virtual Methods
```cpp
virtual void start_receiver() = 0;
virtual void stop_receiver() = 0;
virtual std::tuple<CUdeviceptr, std::shared_ptr<Metadata>> get_next_frame(double timeout_ms) = 0;
virtual std::tuple<std::string, uint32_t> local_ip_and_port();
virtual void timeout(holoscan::InputContext& input, holoscan::OutputContext& output,
                    holoscan::ExecutionContext& context);
```

#### ReceiverMemoryDescriptor Class
```cpp
class ReceiverMemoryDescriptor {
    explicit ReceiverMemoryDescriptor(CUcontext context, size_t size);
    ReceiverMemoryDescriptor() = delete;
    ~ReceiverMemoryDescriptor();
    
    CUdeviceptr get();
};
```

---

### 2. **SIPLCaptureOp Class**

**Purpose:** Camera capture operator using NVIDIA SIPL (Sensor Input Processing Library).

#### Constructor
```cpp
template <typename... ArgsT>
explicit SIPLCaptureOp(const std::string& camera_config, 
                       const std::string& json_config, 
                       bool raw_output, 
                       ArgsT&&... args);
```

#### Lifecycle Methods
```cpp
void setup(holoscan::OperatorSpec& spec) override;
void start() override;
void stop() override;
void compute(holoscan::InputContext& op_input,
            holoscan::OutputContext& op_output,
            holoscan::ExecutionContext& context) override;
```

#### Camera Information
```cpp
struct CameraInfo {
    std::string output_name;
    uint32_t offset;
    uint32_t width;
    uint32_t height;
    uint32_t bytes_per_line;
    hololink::csi::PixelFormat pixel_format;
    hololink::csi::BayerFormat bayer_format;
};

const std::vector<CameraInfo>& get_camera_info();
```

#### Static Utility Methods
```cpp
static void list_available_configs(const std::string& json_config = "");
static nvidia::gxf::Expected<void> buffer_release_callback(void* pointer);
```

#### Parameters
```cpp
holoscan::Parameter<uint32_t> capture_queue_depth_;
holoscan::Parameter<std::string> nito_base_path_;
holoscan::Parameter<uint32_t> timeout_;
```

---

### 3. **ImageProcessorOp Class**

**Purpose:** CUDA-based image processing operator for color conversion, histogram, white balance, etc.

#### Class Definition
```cpp
class ImageProcessorOp : public holoscan::Operator {
    HOLOSCAN_OPERATOR_FORWARD_ARGS(ImageProcessorOp);
    
    void setup(holoscan::OperatorSpec& spec) override;
    void start() override;
    void stop() override;
    void compute(holoscan::InputContext&, holoscan::OutputContext& op_output, 
                holoscan::ExecutionContext&) override;
};
```

#### Parameters
```cpp
holoscan::Parameter<int> pixel_format_;
holoscan::Parameter<int> bayer_format_;
holoscan::Parameter<int32_t> optical_black_;
holoscan::Parameter<int> cuda_device_ordinal_;
```

#### CUDA Resources
```cpp
CUcontext cuda_context_;
CUdevice cuda_device_;
bool is_integrated_;
holoscan::CudaStreamHandler cuda_stream_handler_;
std::shared_ptr<hololink::common::CudaFunctionLauncher> cuda_function_launcher_;
hololink::common::UniqueCUdeviceptr histogram_memory_;
hololink::common::UniqueCUdeviceptr white_balance_gains_memory_;
uint32_t histogram_threadblock_size_;
```

---

## Sensors Module

### Overview
The sensors module provides abstractions for hardware sensors, particularly cameras with CSI/MIPI interfaces.

---

### 1. **Sensor Base Class**

**Purpose:** Abstract interface for all sensor implementations.

```cpp
class Sensor {
    Sensor() = default;
    virtual ~Sensor() = default;
    
    // Lifecycle
    virtual void start() = 0;
    virtual void stop() = 0;
    
protected:
    std::string sensor_id_;  // Unique identifier
};
```

---

### 2. **CameraSensor Class**

**Purpose:** Base class for camera sensors with mode configuration.

#### Class Definition
```cpp
class CameraSensor : public Sensor {
    CameraSensor();
    virtual ~CameraSensor();
    
    // Lifecycle
    void start() override;
    void stop() override;
    
    // Configuration
    virtual void configure(CameraMode mode);
    virtual CameraMode get_mode() const;
    virtual void set_mode(CameraMode mode);
    virtual const std::unordered_set<CameraMode>& supported_modes() const;
    virtual void configure_converter(std::shared_ptr<hololink::csi::CsiConverter> converter);
    
    // Properties
    virtual int64_t get_width() const;
    virtual int64_t get_height() const;
    virtual hololink::csi::PixelFormat get_pixel_format() const;
    virtual hololink::csi::BayerFormat get_bayer_format() const;
};
```

#### Protected Members
```cpp
std::unordered_set<CameraMode> supported_modes_;
std::optional<CameraMode> mode_;
int64_t width_;
int64_t height_;
hololink::csi::PixelFormat pixel_format_;
hololink::csi::BayerFormat bayer_format_;
```

---

### 3. **CameraMode & CameraFrameFormat Classes**

**Purpose:** Camera mode definitions and frame format specifications.

#### CameraMode Type
```cpp
using CameraMode = int;
```

#### CameraFrameFormat Class
```cpp
class CameraFrameFormat {
    struct Format {
        CameraMode mode_id;
        std::string mode_name;
        int64_t width;
        int64_t height;
        double frame_rate;
        csi::PixelFormat pixel_format;
    };
    
    CameraFrameFormat(CameraMode mode_id,
                     const std::string& mode_name,
                     int64_t width,
                     int64_t height,
                     double frame_rate,
                     csi::PixelFormat pixel_format);
    
    virtual ~CameraFrameFormat() = default;
    
    virtual const Format& format() const;
    
    // Convenience accessors
    CameraMode mode_id() const;
    const std::string& mode_name() const;
    int64_t width() const;
    int64_t height() const;
    double frame_rate() const;
    hololink::csi::PixelFormat pixel_format() const;
};
```

---

### 4. **I2C Expander for Camera Power Control**

#### LII2CExpander Class
```cpp
enum class I2CExpanderOutputEN : uint8_t {
    OUTPUT_1 = 0b0001,  // First camera
    OUTPUT_2 = 0b0010,  // Second camera
    OUTPUT_3 = 0b0100,
    OUTPUT_4 = 0b1000,
    DEFAULT = 0b0000
};

class LII2CExpander {
    static constexpr uint32_t I2C_EXPANDER_ADDRESS = 0b01110000;
    
    LII2CExpander(Hololink& hololink, uint32_t i2c_bus);
    void configure(I2CExpanderOutputEN output_en = I2CExpanderOutputEN::DEFAULT);
};
```

---

## Usage Patterns & Integration

### 1. **Device Discovery and Connection Flow**

```cpp
// Step 1: Enumerate devices
hololink::Enumerator enumerator;
hololink::Enumerator::enumerated([&](hololink::Metadata& metadata) {
    // Found a device
    return false; // Stop enumeration
});

// Step 2: Create Hololink instance
auto hololink = hololink::Hololink::from_enumeration_metadata(metadata);

// Step 3: Start communication
hololink->start();

// Step 4: Create data channel
auto data_channel = std::make_unique<hololink::DataChannel>(metadata);

// Step 5: Configure data plane (RoCe or COE)
data_channel->configure_roce(frame_memory, frame_size, page_size, num_pages, data_port);

// Step 6: Use sensor and data plane
hololink::DataChannel::use_sensor(metadata, 0);
hololink::DataChannel::use_data_plane_configuration(metadata, 0);
```

### 2. **I2C Transaction Pattern**

```cpp
auto i2c = hololink->get_i2c(BL_I2C_BUS, I2C_CTRL);
auto lock = std::make_unique<hololink::Hololink::NamedLock>(*hololink, "i2c_bus_0");
lock->lock();

try {
    std::vector<uint8_t> write_bytes = {0x10, 0x20};
    auto result = i2c->i2c_transaction(0x50, write_bytes, 4, timeout);
    // Process result
} catch (const std::exception& e) {
    // Handle error
}

lock->unlock();
```

### 3. **Register Read/Write Pattern**

```cpp
auto timeout = std::make_shared<hololink::Timeout>(5.0f, 0.1f); // 5s timeout, 100ms retry

// Single register write
if (hololink->write_uint32(0x80, 0xDEADBEEF, timeout)) {
    std::cout << "Write successful\n";
}

// Batched writes
hololink::Hololink::WriteData batch;
batch.queue_write_uint32(0x80, 0x12345678);
batch.queue_write_uint32(0x84, 0x9ABCDEF0);
hololink->write_uint32(batch, timeout);

// Register read
uint32_t value = hololink->read_uint32(0x80, timeout);

// Block read
auto [success, values] = hololink->read_uint32(0x80, 16, timeout);
```

### 4. **Sequencer Pattern (Event-Synchronized Operations)**

```cpp
auto sequencer = hololink->software_sequencer();

// Build a sequence of operations
unsigned write_idx = sequencer->write_uint32(I2C_ADDR, I2C_VALUE);
unsigned read_idx = sequencer->read_uint32(STATUS_ADDR);
unsigned poll_idx = sequencer->poll(STATUS_ADDR, 0xFF, READY_VALUE);

// Configure to run on frame-end event
sequencer->enable();
hololink->configure_apb_event(hololink::Hololink::Event::SIF_0_FRAME_END, 
                              sequencer->location());
```

### 5. **Camera Sensor Integration Pattern**

```cpp
// Create camera sensor
auto camera = std::make_shared<hololink::sensors::CameraSensor>();

// Configure CSI converter (for parsing received data)
auto converter = /* create converter instance */;
camera->configure_converter(converter);

// Set mode
camera->set_mode(CAMERA_MODE_4K_60FPS);

// Start acquisition
camera->start();

// Process frames...

// Stop acquisition
camera->stop();
```

### 6. **Holoscan Operator Integration Pattern**

```cpp
class MyReceiverOp : public hololink::operators::BaseReceiverOp {
    void start_receiver() override {
        // Initialize receiver
    }
    
    void stop_receiver() override {
        // Cleanup receiver
    }
    
    std::tuple<CUdeviceptr, std::shared_ptr<hololink::Metadata>> 
    get_next_frame(double timeout_ms) override {
        // Wait for and return next frame
        return std::make_tuple(device_ptr, metadata);
    }
};

// In Holoscan pipeline:
auto op = builder.make_operator<MyReceiverOp>(
    "receiver",
    make_condition<AsynchronousCondition>(),
    Arg("hololink_channel", &data_channel),
    Arg("frame_context", context),
    Arg("frame_size", frame_size_bytes)
);
```

---

## Type Definitions & Constants

### Memory and Alignment Constants
```cpp
constexpr uint32_t METADATA_SIZE = 128;
constexpr uint32_t PAGE_SIZE = 128;  // I/O alignment
constexpr uint32_t UDP_PACKET_SIZE = 10240;
```

### Communication Parameters
```cpp
constexpr uint16_t DATA_SOURCE_UDP_PORT = 12288;
```

### SPI Bus Configuration
```cpp
constexpr uint32_t SPI_CTRL = 0x0300'0000;
constexpr uint32_t RESET_SPI_BUS = 0;
constexpr uint32_t CLNX_SPI_BUS = 0;
constexpr uint32_t CPNX_SPI_BUS = 1;
```

### I2C Bus Configuration
```cpp
constexpr uint32_t BL_I2C_BUS = 0;
constexpr uint32_t CAM_I2C_BUS = 1;
constexpr uint32_t I2C_CTRL = 0x0300'0200;
```

### VSYNC Control Registers
```cpp
constexpr uint32_t VSYNC_CONTROL = 0x70000000;
constexpr uint32_t VSYNC_FREQUENCY = 0x70000004;
constexpr uint32_t VSYNC_DELAY = 0x70000008;
constexpr uint32_t VSYNC_START = 0x7000000C;
constexpr uint32_t VSYNC_EXPOSURE = 0x70000010;
constexpr uint32_t VSYNC_GPIO = 0x70000014;
```

### PTP (Precision Time Protocol) Registers
```cpp
constexpr uint32_t FPGA_PTP_CTRL = 0x104;
constexpr uint32_t FPGA_PTP_DELAY_ASYMMETRY = 0x10C;
constexpr uint32_t FPGA_PTP_CTRL_DPLL_CFG1 = 0x110;
constexpr uint32_t FPGA_PTP_CTRL_DPLL_CFG2 = 0x114;
constexpr uint32_t FPGA_PTP_CTRL_DELAY_AVG_FACTOR = 0x118;
constexpr uint32_t FPGA_PTP_SYNC_TS_0 = 0x180;
constexpr uint32_t FPGA_PTP_SYNC_STAT = 0x188;
constexpr uint32_t FPGA_PTP_OFM = 0x18C;
```

### Data Channel Registers
```cpp
constexpr uint32_t DP_PACKET_SIZE = 0x04;
constexpr uint32_t DP_PACKET_UDP_PORT = 0x08;
constexpr uint32_t DP_VP_MASK = 0x0C;
constexpr uint32_t DP_BUFFER_LENGTH = 0x18;
constexpr uint32_t DP_BUFFER_MASK = 0x1C;
constexpr uint32_t DP_HOST_MAC_LOW = 0x20;
constexpr uint32_t DP_HOST_MAC_HIGH = 0x24;
constexpr uint32_t DP_HOST_IP = 0x28;
constexpr uint32_t DP_HOST_UDP_PORT = 0x2C;
```

### Board IDs (Legacy - Use UUID instead)
```cpp
constexpr uint32_t HOLOLINK_LITE_BOARD_ID = 2u;
constexpr uint32_t HOLOLINK_100G_BOARD_ID = 3u;
constexpr uint32_t MICROCHIP_POLARFIRE_BOARD_ID = 4u;
constexpr uint32_t HOLOLINK_NANO_BOARD_ID = 5u;
constexpr uint32_t LEOPARD_EAGLE_BOARD_ID = 7u;
```

### Packet Command Bytes
```cpp
constexpr uint32_t WR_DWORD = 0x04;      // Write single register
constexpr uint32_t WR_BLOCK = 0x09;      // Write multiple registers
constexpr uint32_t RD_DWORD = 0x14;      // Read single register
constexpr uint32_t RD_BLOCK = 0x19;      // Read multiple registers
```

### Response Codes
```cpp
constexpr uint32_t RESPONSE_SUCCESS = 0x00;
constexpr uint32_t RESPONSE_ERROR_GENERAL = 0x02;
constexpr uint32_t RESPONSE_INVALID_ADDR = 0x03;
constexpr uint32_t RESPONSE_INVALID_CMD = 0x04;
constexpr uint32_t RESPONSE_INVALID_PKT_LENGTH = 0x05;
constexpr uint32_t RESPONSE_INVALID_FLAGS = 0x06;
constexpr uint32_t RESPONSE_BUFFER_FULL = 0x07;
constexpr uint32_t RESPONSE_INVALID_BLOCK_SIZE = 0x08;
constexpr uint32_t RESPONSE_COMMAND_TIMEOUT = 0x0A;
constexpr uint32_t RESPONSE_SEQUENCE_CHECK_FAIL = 0x0B;
```

### Logging Levels
```cpp
enum HsbLogLevel {
    HSB_LOG_LEVEL_TRACE = 10,
    HSB_LOG_LEVEL_DEBUG = 20,
    HSB_LOG_LEVEL_INFO = 30,
    HSB_LOG_LEVEL_WARN = 40,
    HSB_LOG_LEVEL_ERROR = 50,
    HSB_LOG_LEVEL_INVALID = 0
};

extern HsbLogLevel hsb_log_level;
extern HsbLogger hsb_logger;  // Customizable callback
```

---

## Summary

This documentation covers:

- **Core Module**: Device communication (Hololink), data planes (DataChannel), device discovery (Enumerator), timing and retry logic (Timeout), binary marshaling (Serializer/Deserializer), and peripheral interfaces (I2C, SPI, GPIO)

- **Common Module**: Command-line argument parsing (Holoargs), CUDA integration (CudaHelper), and GUI rendering (ImGuiRenderer)

- **Operators Module**: Base data reception (BaseReceiverOp), SIPL camera capture (SIPLCaptureOp), and image processing (ImageProcessorOp)

- **Sensors Module**: Abstract sensor interface, camera sensor implementations with mode management and CSI configuration, I2C expander for power control

Each module provides a complete abstraction layer enabling applications to:
1. Discover and enumerate HSB devices
2. Configure data planes for high-speed data transfer (RoCe/UDP/COE)
3. Control camera sensors and peripheral devices (I2C/SPI/GPIO)
4. Integrate with Holoscan for dataflow-based application development
5. Perform image acquisition and processing with CUDA acceleration
