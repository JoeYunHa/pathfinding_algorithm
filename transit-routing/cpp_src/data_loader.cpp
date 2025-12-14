#include "data_loader.h"
#include "utils.h"
#include <algorithm>
#include <mutex>
#include <iostream>

namespace pathfinding
{
    void DataContainer::load_from_python(
        const py::dict &stations_dict, const py::dict &line_stations_dict,
        const py::dict &station_order_dict, const py::dict &transfers_dict,
        const py::dict &congestion_dict)
    {
        // 1. Stations 로드
        size_t count = stations_dict.size();
        stations_.reserve(count);
        id_to_code_.reserve(count);
        station_lines_.resize(count);
        station_scores_.assign(count, {0.0, 0.0, 0.0, 0.0});

        StationID current_id = 0;
        for (auto item : stations_dict)
        {
            std::string cd = py::str(item.first);
            if (code_to_id_.find(cd) == code_to_id_.end())
            {
                code_to_id_[cd] = current_id;
                id_to_code_.push_back(cd);

                py::dict info = item.second.cast<py::dict>();
                StationInfo s;
                s.id = current_id;
                s.station_cd = cd;
                s.name = py::str(info["name"]);
                s.line = py::str(info["line"]);
                s.latitude = info["latitude"].cast<double>();
                s.longitude = info["longitude"].cast<double>();

                stations_.push_back(s);
                current_id++;
            }
        }

        // Station Lines 구축 => 이름이 같으면 모든 노선을 다 넣어버림
        // for (const auto &s : stations_)
        // {
        //     for (const auto &t : stations_)
        //     {
        //         if (s.name == t.name)
        //             station_lines_[s.id].push_back(t.line);
        //     }
        // }
        // 자기 자신의 노선만 등록 (환승은 transfers_ 맵을 통해서만 이동)
        for (const auto &s : stations_)
        {
            station_lines_[s.id].push_back(s.line);
        }

        // 2. Station Order (중간역 복원용)
        for (auto item : station_order_dict)
        {
            py::tuple key = item.first.cast<py::tuple>();
            std::string cd = py::str(key[0]);
            std::string line = py::str(key[1]);
            int order = item.second.cast<int>();

            if (code_to_id_.find(cd) != code_to_id_.end())
            {
                StationID sid = code_to_id_[cd];
                station_orders_[{sid, line}] = order;
                line_ordered_stations_[line].push_back({order, sid});
            }
        }
        for (auto &kv : line_ordered_stations_)
        {
            std::sort(kv.second.begin(), kv.second.end());
        }

        // 3. Line Topology
        for (auto item : line_stations_dict)
        {
            py::tuple key = item.first.cast<py::tuple>();
            std::string cd = py::str(key[0]);
            std::string line = py::str(key[1]);

            if (code_to_id_.find(cd) == code_to_id_.end())
                continue;
            StationID sid = code_to_id_[cd];

            py::dict dirs = item.second.cast<py::dict>();
            DirectionLines dl;
            if (dirs.contains("up"))
            {
                for (auto n : dirs["up"].cast<py::list>())
                {
                    std::string n_cd = py::str(n);
                    if (code_to_id_.count(n_cd))
                        dl.up.push_back(code_to_id_[n_cd]);
                }
            }
            if (dirs.contains("down"))
            {
                for (auto n : dirs["down"].cast<py::list>())
                {
                    std::string n_cd = py::str(n);
                    if (code_to_id_.count(n_cd))
                        dl.down.push_back(code_to_id_[n_cd]);
                }
            }
            line_topology_[{sid, line}] = dl;
        }

        // 4. Transfers (거리 + 환승역 정보)
        std::unordered_map<std::string, std::vector<StationID>> name_to_ids;
        for (const auto &s : stations_)
        {
            name_to_ids[s.name].push_back(s.id);
        }

        for (auto item : transfers_dict)
        {
            py::tuple key = item.first.cast<py::tuple>();
            std::string from_cd = py::str(key[0]);

            // 출발 역 코드가 유효하지 않으면 패스
            if (code_to_id_.find(from_cd) == code_to_id_.end())
                continue;

            StationID from_sid = code_to_id_[from_cd];
            std::string f_line = py::str(key[1]); // 출발 노선
            std::string t_line = py::str(key[2]); // 목적지 노선 (환승할 노선)

            py::dict val = item.second.cast<py::dict>();

            TransferData td;
            td.distance = val["distance"].cast<double>();

            // 목적지 역 ID(to_station_id) 찾기
            // 현재 역(from_sid)과 이름이 같으면서, 노선이 t_line인 역을 찾습니다.
            bool target_found = false;
            std::string current_station_name = stations_[from_sid].name;

            // 해당 이름(예: 서울역)을 가진 모든 역 ID를 순회
            if (name_to_ids.find(current_station_name) != name_to_ids.end())
            {
                for (StationID candidate_id : name_to_ids[current_station_name])
                {
                    // 후보 역의 노선이 우리가 갈아타려는 노선(t_line)과 같다면 빙고!
                    if (stations_[candidate_id].line == t_line)
                    {
                        td.to_station_id = candidate_id;
                        target_found = true;
                        break;
                    }
                }
            }

            if (target_found)
            {
                // 목적지를 찾았을 때만 환승 정보를 등록합니다.
                transfers_[{from_sid, f_line, t_line}] = td;
            }
            else
            {
                // 디버깅 -> 데이터 정합성 문제로 환승 대상을 못 찾음
                // std::cerr << "[WARN] Transfer target missing: " << current_station_name
                //           << " (" << f_line << " -> " << t_line << ")" << std::endl;
            }
        }

        // 5. Congestion
        for (auto item : congestion_dict)
        {
            py::tuple key = item.first.cast<py::tuple>();
            std::string cd = py::str(key[0]);
            if (code_to_id_.find(cd) == code_to_id_.end())
                continue;

            StationID sid = code_to_id_[cd];
            std::string line = py::str(key[1]);
            std::string dir_str = py::str(key[2]);
            std::string day = py::str(key[3]);
            Direction dir = PathfindingUtils::str_to_direction(dir_str);

            py::dict slots = item.second.cast<py::dict>();
            std::unordered_map<std::string, double> slot_map;
            for (auto slot : slots)
            {
                slot_map[py::str(slot.first)] = slot.second.cast<double>();
            }
            congestion_[{sid, line, dir, day}] = slot_map;
        }
    }

    void DataContainer::update_facility_scores(const py::list &facility_rows)
    {
        std::unique_lock<std::shared_mutex> lock(update_mutex);

        for (auto &row_obj : facility_rows)
        {
            py::dict row = row_obj.cast<py::dict>();
            py::list cd_list = row["station_cd_list"].cast<py::list>();

            double charger = row["charger_count"].cast<double>();
            double elevator = row["elevator_count"].cast<double>();
            double escalator = row["escalator_count"].cast<double>();
            double lift = row["lift_count"].cast<double>();
            double movingwalk = row["movingwalk_count"].cast<double>();
            double safe_platform = row["safe_platform_count"].cast<double>();
            double sign_phone = row["sign_phone_count"].cast<double>();
            double toilet = row["toilet_count"].cast<double>();
            double helper = row["helper_count"].cast<double>();

            std::array<double, 4> calc_scores;
            for (int i = 0; i < 4; ++i)
            {
                DisabilityType type = static_cast<DisabilityType>(i);
                const auto &w = PathfindingUtils::get_facility_weights(type);
                double raw = (charger * w.charger) + (elevator * w.elevator) +
                             (escalator * w.escalator) + (lift * w.lift) +
                             (movingwalk * w.movingwalk) + (safe_platform * w.safe_platform) +
                             (sign_phone * w.sign_phone) + (toilet * w.toilet) +
                             (helper * w.helper);
                calc_scores[i] = PathfindingUtils::normalize_score(raw);
            }

            for (auto &cd_obj : cd_list)
            {
                std::string cd = py::str(cd_obj);
                auto it = code_to_id_.find(cd);
                if (it != code_to_id_.end())
                {
                    station_scores_[it->second] = calc_scores;
                }
            }
        }
    }

    std::vector<StationID> DataContainer::get_intermediate_stations(
        StationID from_id, StationID to_id, const std::string &line) const
    {
        std::vector<StationID> result;
        auto it_from = station_orders_.find({from_id, line});
        auto it_to = station_orders_.find({to_id, line});

        if (it_from == station_orders_.end() || it_to == station_orders_.end())
        {
            result.push_back(to_id);
            return result;
        }

        int from_order = it_from->second;
        int to_order = it_to->second;
        bool ascending = from_order < to_order;

        auto it_list = line_ordered_stations_.find(line);
        if (it_list == line_ordered_stations_.end())
        {
            result.push_back(to_id);
            return result;
        }
        const auto &list = it_list->second;

        if (ascending)
        {
            for (const auto &p : list)
            {
                if (p.first > from_order && p.first <= to_order)
                    result.push_back(p.second);
            }
        }
        else
        {
            for (auto it = list.rbegin(); it != list.rend(); ++it)
            {
                if (it->first < from_order && it->first >= to_order)
                    result.push_back(it->second);
            }
        }
        if (result.empty())
            result.push_back(to_id);
        return result;
    }

    StationID DataContainer::get_id(const std::string &cd) const
    {
        auto it = code_to_id_.find(cd);
        if (it != code_to_id_.end())
            return it->second;
        throw std::runtime_error("Unknown station code: " + cd);
    }

    std::string DataContainer::get_code(StationID id) const
    {
        if (id < id_to_code_.size())
            return id_to_code_[id];
        return "";
    }

    // const StationInfo &DataContainer::get_station(StationID id) const
    // {
    //     return stations_[id];
    // }

    // const std::vector<std::string> &DataContainer::get_lines(StationID id) const
    // {
    //     return station_lines_[id];
    // }

    const DataContainer::DirectionLines &DataContainer::get_next_stations(StationID id, const std::string &line) const
    {
        static const DirectionLines empty;
        auto it = line_topology_.find({id, line});
        if (it != line_topology_.end())
            return it->second;
        return empty;
    }

    const TransferData *DataContainer::get_transfer(StationID from, const std::string &f_line, const std::string &t_line) const
    {
        auto it = transfers_.find({from, f_line, t_line});
        if (it != transfers_.end())
            return &it->second;
        return nullptr;
    }

    double DataContainer::get_congestion(StationID id, const std::string &line, Direction dir,
                                         const std::string &day, const std::string &time_col) const
    {
        auto it = congestion_.find({id, line, dir, day});
        if (it != congestion_.end())
        {
            auto sit = it->second.find(time_col);
            if (sit != it->second.end())
                return sit->second;
        }
        return 0.5;
    }
}