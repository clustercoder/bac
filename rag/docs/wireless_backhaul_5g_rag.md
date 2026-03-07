1. Overview

Wireless backhaul networks connect access networks to the core network through wired or wireless links. In future 5G systems, the backhaul network must support:

high capacity

low latency

reliability

scalability

The increasing demand for applications such as UHD video streaming, cloud services, and connected devices requires new backhaul architectures capable of handling dense small-cell deployments. 

Jialu Lun PhD Thesis

2. Motivation

Future networks must support:

Ultra High Definition (UHD) video streaming

Cloud gaming

Device-to-device communication

Machine-to-machine (M2M) systems

These applications increase:

traffic volume

latency sensitivity

coordination requirements among base stations

Therefore, innovative backhaul architectures and resource management mechanisms are required to support these network demands. 

Jialu Lun PhD Thesis

3. Key Performance Indicators in 5G Networks

Important KPIs used to evaluate network performance include:

User Perceived Throughput

Measured in Mbps and represents the experienced data rate available to a user.

Area Traffic Capacity

Measured in Mbps/km² and represents the total traffic capacity available in a geographic area.

Latency

The time required for a data packet to travel across the network.

Mobility

The maximum speed at which a user device can move while maintaining acceptable QoS. 

Jialu Lun PhD Thesis

4. Dense Small Cell Networks

Small cells are low-power base stations used to increase network capacity.

Types include:

femtocells

picocells

microcells

Small cells typically cover areas ranging from tens to hundreds of meters and are deployed in dense urban environments.

These deployments create heterogeneous networks (HetNets) that combine different cell sizes and technologies. 

Jialu Lun PhD Thesis

5. Interference Management

Large-scale deployment of small cells increases the likelihood of interference.

Two major technologies address this issue:

Enhanced Inter-Cell Interference Coordination (eICIC)

This technique uses:

Almost Blank Subframes (ABS)

Cell Range Expansion (CRE)

These methods reduce interference between macro cells and small cells.

Coordinated Multipoint (CoMP)

CoMP allows multiple geographically separated nodes to coordinate transmissions to improve signal quality.

Two primary CoMP categories are:

Joint Processing (JP)

Multiple transmission points simultaneously send data to a user.

Advantages:

improved signal-to-interference ratio

increased throughput

Disadvantages:

high backhaul bandwidth requirements

strict synchronization requirements

Coordinated Scheduling / Beamforming (CS/CB)

Transmission scheduling and beamforming are coordinated to minimize interference while data is transmitted from a single node. 

Jialu Lun PhD Thesis

6. User Association in Small Cell Networks

User association determines which base station serves a device.

Typical decision factors include:

signal strength (RSRP)

signal quality (RSRQ)

available bandwidth

traffic type

However, many current models ignore:

backhaul capacity constraints

user mobility patterns

Future systems must incorporate these factors into user association algorithms. 

Jialu Lun PhD Thesis

7. Wireless Backhaul Technologies

Several frequency bands can be used for wireless backhaul.

Sub-1 GHz Band

Advantages:

wide coverage

good propagation characteristics

Example:

Television White Space (TVWS)

Limitations:

strict power regulations

spectrum sharing constraints.

1–6 GHz Band

Advantages:

non-line-of-sight capability

widespread deployment in cellular systems

Example:

3.5 GHz band

However, this spectrum range is limited and cannot always support high-capacity 5G demands. 

Jialu Lun PhD Thesis

Millimeter Wave (mmWave)

Frequency range:

60 GHz

70–80 GHz

Advantages:

large available spectrum

multi-gigabit data rates

Limitations:

rain attenuation

beam misalignment

line-of-sight requirement

To improve reliability, systems may use:

multi-hop relays

redundant links

hybrid microwave/mmWave links. 

Jialu Lun PhD Thesis

Free Space Optics (FSO)

FSO transmits data using laser light.

Advantages:

high bandwidth

license-free operation

relatively low cost

Limitations:

affected by fog and snow

requires precise alignment

limited range

Hybrid FSO and mmWave systems can improve reliability under varying environmental conditions. 

Jialu Lun PhD Thesis

8. Backhaul Topologies

Different topologies provide trade-offs between reliability, cost, and complexity.

Tree Topology

Combination of star and chain structures.

Advantages:

simpler management

cost efficiency

Ring Topology

Nodes are connected in a loop.

Advantages:

redundancy

resilience

Mesh Topology

Each node connects to multiple nodes.

Advantages:

high robustness

multiple routing paths

Disadvantages:

higher cost

increased complexity in network management. 

Jialu Lun PhD Thesis

9. Energy Efficiency in Wireless Networks

Network densification increases energy consumption.

Energy efficiency improvements include:

efficient power amplifiers

advanced antenna systems

adaptive resource allocation

dynamic base station activation

Base stations can be activated or deactivated based on traffic demand to reduce overall energy usage. 

Jialu Lun PhD Thesis

10. Cloud Technologies in Backhaul Networks

Cloud-based architectures improve resource management and scalability.

Cloud-RAN (C-RAN)

C-RAN centralizes baseband processing in a shared pool.

Advantages:

improved resource utilization

reduced hardware cost

enhanced coordination between cells

However, C-RAN requires:

high data rates

low latency fronthaul links

Fiber is typically used to connect remote radio heads (RRHs) with the baseband unit (BBU) pool. 

Jialu Lun PhD Thesis

11. Network Virtualisation

Network virtualization allows multiple logical networks to share the same physical infrastructure.

Benefits include:

increased resource utilization

reduced operational costs

flexible service deployment

Two main participants in this model are:

Infrastructure Providers

Own and manage the physical network resources.

Service Providers

Lease virtual network resources to deliver services to customers. 

Jialu Lun PhD Thesis

12. Software Defined Networking (SDN)

SDN separates the control plane from the data plane.

This architecture contains three layers.

Infrastructure Layer

Consists of network devices such as switches and routers that forward packets and collect traffic statistics.

Control Layer

Contains centralized controllers responsible for:

managing network behavior

configuring routing rules

monitoring network status

Application Layer

Provides interfaces for network applications to define policies and control algorithms. 

Jialu Lun PhD Thesis

13. Two-Tier SDN Controller Architecture

To improve scalability, the thesis proposes a two-tier controller architecture:

Central Controller

Responsibilities:

network-wide decision making

global topology management

policy enforcement

Local Controllers

Responsibilities:

handling time-critical tasks

managing localized network segments

reducing load on the central controller

This hierarchical design balances system performance and scalability. 

Jialu Lun PhD Thesis

14. Multi-Tenancy Resource Sharing

Backhaul networks may serve multiple infrastructure providers simultaneously.

Resource sharing mechanisms enable:

fair bandwidth allocation

quality-of-service guarantees

efficient utilization of network capacity

SDN enables dynamic reconfiguration of these resources. 

Jialu Lun PhD Thesis

15. Topology Management

Backhaul topology management must consider:

traffic distribution

latency constraints

resource utilization

QoS requirements

Dynamic topology management algorithms allow networks to adapt to changing traffic conditions and maintain service quality. 

Jialu Lun PhD Thesis

16. Multi-Hop Backhaul Networks

Multi-hop architectures extend network coverage and distribute traffic load.

Advantages:

improved coverage

increased resilience

flexible deployment

However, multi-hop networks introduce:

additional latency

routing complexity

Therefore, intelligent topology management is required to maintain QoS. 

Jialu Lun PhD Thesis

17. Conclusions

Future wireless backhaul networks must support:

high capacity

flexibility

scalability

efficient resource utilization

Technologies such as:

SDN

network virtualization

mmWave communication

multi-hop topologies

will play a critical role in enabling next-generation 5G network architectures.